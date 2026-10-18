// File: frontend/src/config/wake.js
// Purpose: REQ-GHA-018 on-demand settings, all from the build environment.
//   VITE_API_BASE    — the API's address when the app is served from app.glasshood.ai
//                      (unset: same origin, as today)
//   VITE_CONTROLLER  — the wake controller's address (unset: no wake/sleep at all)
//   VITE_RECAPTCHA_SITE_KEY — reCAPTCHA v3 key used to renew the use token

export function wakeConfig(env) {
  const strip = (v) => (v || '').replace(/\/+$/, '')
  return {
    apiBase: strip(env?.VITE_API_BASE),
    controller: strip(env?.VITE_CONTROLLER),
    recaptchaSiteKey: env?.VITE_RECAPTCHA_SITE_KEY || '',
    wakingPage: '/waking/',
  }
}

export const WAKE = wakeConfig(import.meta.env)

// Where an asleep visitor is sent: the waking page, told where to come back to.
export function wakingPageUrl(loc, wakingPage = WAKE.wakingPage) {
  const back = `${loc.pathname}${loc.search}${loc.hash}`
  return `${wakingPage}?next=${encodeURIComponent(back)}`
}
