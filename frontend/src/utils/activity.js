// File: frontend/src/utils/activity.js
// Purpose: REQ-GHA-018 clause 7 — tell the wake controller when a person uses the
// app, so it sleeps after 2 hours without use. Only person-caused events count:
// loading the app (covers reload and opening any route), route changes, login,
// pointer-down and key-down. Background polling never calls this, and nothing is
// sent while the tab is hidden, so an untouched tab stops counting. Failed
// background requests stay passive: only a visit or a person-caused event may go
// to the waking page (which wakes the app).
//
// The use token comes from the waking page (sessionStorage 'glasshood_use_token',
// JSON {use_token, use_token_expires}). It is renewed only while sending a use and
// only through a fresh reCAPTCHA, so a copied token cannot renew itself; renewal
// itself is not use. A tab opened while the app is already awake, or holding a
// token from an earlier wake, gets a new one the same way.

import { WAKE, wakingPageUrl } from '../config/wake.js'

export const USE_THROTTLE_MS = 60_000
export const RENEW_BEFORE_MS = 30 * 60_000
export const CONTROLLER_TIMEOUT_MS = 10_000
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

// fetch, then read the JSON body, all within ms: a controller that stalls on the
// headers or on the body ends in an error instead of a promise that never settles.
export async function fetchJsonWithin(fetchFn, url, init, ms = CONTROLLER_TIMEOUT_MS,
                                      setTimer = setTimeout, clearTimer = clearTimeout) {
  const ctl = new AbortController()
  let timer
  const timeout = new Promise((_, reject) => {
    timer = setTimer(() => { ctl.abort(); reject(new Error('controller timeout')) }, ms)
  })
  const call = (async () => {
    const resp = await fetchFn(url, { ...init, signal: ctl.signal })
    let body = null
    if (resp.status !== 204) {
      try { body = await resp.json() } catch { body = null }
    }
    return { status: resp.status, body }
  })()
  try {
    return await Promise.race([call, timeout])
  } finally {
    clearTimer(timer)
  }
}

// The wake controller as seen from the app. Everything it needs is passed in, so
// tests run it without a browser.
//   checkAwake()  a visit or person-caused action: true when awake, otherwise the
//                 tab goes to the waking page (which shows progress and failures).
//                 Background work never calls it.
//   sendUse()     report one person-caused use (skipped while the tab is hidden).
export function createWakeClient({ controller, fetchFn, storage, loc, recaptchaToken,
                                   isHidden = () => false, now = () => Date.now(),
                                   timeoutMs = CONTROLLER_TIMEOUT_MS,
                                   setTimer = setTimeout, clearTimer = clearTimeout }) {
  const call = (path, init) =>
    fetchJsonWithin(fetchFn, `${controller}${path}`, { cache: 'no-store', ...init }, timeoutMs, setTimer, clearTimer)
  const post = (path, body) =>
    call(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

  async function checkAwake() {
    try {
      const { body } = await call('/status')
      if (body?.state === 'awake') return true
    } catch {
      // Unreachable or too slow: the waking page shows the failure and how to get help.
    }
    loc.replace(wakingPageUrl(loc))
    return false
  }

  // A new use token, only ever through a fresh reCAPTCHA. Renewal is not use.
  async function renew() {
    try {
      const { status, body } = await post('/wake', { recaptcha_token: await recaptchaToken() })
      if (status === 202 && body?.use_token) {
        storeUseToken(body, storage)
        return true
      }
    } catch {
      // No token this time; the next person-caused event tries again.
    }
    return false
  }

  async function postUse(t) {
    return (await post('/use', { use_token: t.use_token })).status
  }

  async function sendUse() {
    if (isHidden()) return
    try {
      let t = readUseToken(storage)
      if (!t) {
        // Opened while already awake, so the waking page never gave this tab a token.
        if (!(await checkAwake()) || !(await renew())) return
        t = readUseToken(storage)
      }
      let status = await postUse(t)
      if (status === 403) {
        // Expired, or from an earlier wake. Asleep: go and wake it. Awake (someone
        // else or a hold kept it up): a fresh reCAPTCHA token, then this use again, once.
        if (!(await checkAwake()) || !(await renew())) return
        t = readUseToken(storage)
        status = await postUse(t)
        if (status === 403) return
      }
      if (status === 204 && Date.parse(t.use_token_expires) - now() < RENEW_BEFORE_MS) await renew()
    } catch {
      // A lost use report is retried by the next person-caused event.
    }
  }

  return { checkAwake, renew, sendUse }
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
      s.onerror = () => { _recaptchaLoading = null; reject(new Error('reCAPTCHA failed to load')) }
      document.head.appendChild(s)
    })
  }
  return _recaptchaLoading
}

let _client = null
function _wake() {
  if (!_client) {
    _client = createWakeClient({
      controller: WAKE.controller,
      fetchFn: (...a) => fetch(...a),
      storage: sessionStorage,
      loc: window.location,
      recaptchaToken: async () => (await _recaptcha()).execute(WAKE.recaptchaSiteKey, { action: 'wake' }),
      isHidden: () => document.visibilityState === 'hidden',
    })
  }
  return _client
}

// Called on load (a visit). Never from background polling or failed API calls.
export async function ensureAwakeOrRedirect() {
  if (!WAKE.controller) return true
  return _wake().checkAwake()
}

const _report = createThrottle(() => { _wake().sendUse() })

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
