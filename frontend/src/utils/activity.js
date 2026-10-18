// File: frontend/src/utils/activity.js
// Purpose: REQ-GHA-018 clause 7 — tell the wake controller when a person uses the
// app, so it sleeps after 2 hours without use. Only person-caused events count:
// loading the app (covers reload and opening any route), route changes, login,
// pointer-down and key-down. Background polling never calls this, and nothing is
// sent while the tab is hidden, so an untouched tab stops counting.
//
// The use token comes from the waking page (sessionStorage 'glasshood_use_token',
// JSON {use_token, use_token_expires}). It is renewed only while sending a use and
// only through a fresh reCAPTCHA, so a copied token cannot renew itself; renewal
// itself is not use. A tab opened while the app is already awake gets its first
// token the same way.

import { WAKE, wakingPageUrl } from '../config/wake.js'

export const USE_THROTTLE_MS = 60_000
export const RENEW_BEFORE_MS = 30 * 60_000
const TOKEN_KEY = 'glasshood_use_token'

export function readUseToken(storage = sessionStorage) {
  try {
    const raw = storage.getItem(TOKEN_KEY)
    if (!raw) return null
    const t = JSON.parse(raw)
    return t && t.use_token ? t : null
  } catch {
    return null
  }
}

export function storeUseToken(t, storage = sessionStorage) {
  try { storage.setItem(TOKEN_KEY, JSON.stringify(t)) } catch { /* private mode */ }
}

// Leading-edge send, then at most one trailing send per window: a use inside the
// window is recorded when the window ends, never dropped.
export function createThrottle(send, windowMs = USE_THROTTLE_MS, now = () => Date.now(),
                               setTimer = setTimeout) {
  let lastSent = -Infinity
  let pending = false
  return function trigger() {
    const t = now()
    if (t - lastSent >= windowMs) {
      lastSent = t
      send()
      return
    }
    if (pending) return
    pending = true
    setTimer(() => {
      pending = false
      lastSent = now()
      send()
    }, lastSent + windowMs - t)
  }
}

let _recaptchaLoading = null
function _recaptcha() {
  if (!WAKE.recaptchaSiteKey) return Promise.reject(new Error('no reCAPTCHA key'))
  if (!_recaptchaLoading) {
    _recaptchaLoading = new Promise((resolve, reject) => {
      const s = document.createElement('script')
      s.src = `https://www.google.com/recaptcha/api.js?render=${encodeURIComponent(WAKE.recaptchaSiteKey)}`
      s.async = true
      s.onload = () => window.grecaptcha.ready(() => resolve(window.grecaptcha))
      s.onerror = () => reject(new Error('reCAPTCHA failed to load'))
      document.head.appendChild(s)
    })
  }
  return _recaptchaLoading
}

async function _renew() {
  const g = await _recaptcha()
  const recaptcha_token = await g.execute(WAKE.recaptchaSiteKey, { action: 'wake' })
  const resp = await fetch(`${WAKE.controller}/wake`, {
    method: 'POST', cache: 'no-store',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ recaptcha_token }),
  })
  if (resp.status === 202) storeUseToken(await resp.json())
}

export async function ensureAwakeOrRedirect(loc = window.location) {
  if (!WAKE.controller) return true
  try {
    const resp = await fetch(`${WAKE.controller}/status`, { cache: 'no-store' })
    const body = await resp.json()
    if (body.state === 'awake') return true
  } catch {
    // Controller unreachable: the waking page shows the failure and how to get help.
  }
  loc.replace(wakingPageUrl(loc))
  return false
}

async function _sendUse() {
  if (!WAKE.controller || document.visibilityState === 'hidden') return
  let t = readUseToken()
  if (!t) {
    // Opened while already awake, so the waking page never gave this tab a token:
    // get one through reCAPTCHA (not itself use), then report this use with it.
    if (!(await ensureAwakeOrRedirect())) return
    try { await _renew() } catch { return }
    t = readUseToken()
    if (!t) return
  }
  try {
    const resp = await fetch(`${WAKE.controller}/use`, {
      method: 'POST', cache: 'no-store',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ use_token: t.use_token }),
    })
    if (resp.status === 403) { await ensureAwakeOrRedirect(); return }
    if (Date.parse(t.use_token_expires) - Date.now() < RENEW_BEFORE_MS) await _renew()
  } catch {
    // A lost use report is retried by the next person-caused event.
  }
}

const _report = createThrottle(() => { _sendUse() })

export function reportUse() {
  if (WAKE.controller) _report()
}

let _started = false
export function startActivityTracking() {
  if (!WAKE.controller || _started) return
  _started = true
  window.addEventListener('pointerdown', reportUse, { capture: true, passive: true })
  window.addEventListener('keydown', reportUse, { capture: true, passive: true })
  window.addEventListener('popstate', reportUse)
  reportUse()
}
