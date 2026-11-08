// File: frontend/src/utils/pollCache.js
// Purpose: REQ-GHA-037 / REQ-GHA-036 — the last answer for each polled path, so a click shows
// that system's own stored view at once. Every answer belongs to one session: a login,
// logout or token change starts a new session, and an answer from an earlier session is
// neither shown nor stored, also when its request finishes after the change.

let epoch = 0
const entries = new Map()

export function sessionEpoch() {
  return epoch
}

// A new login, logout or token: nothing stored so far may be shown any more
export function newSession() {
  epoch++
  entries.clear()
}

export function stored(path) {
  const e = entries.get(path)
  return e && e.epoch === epoch ? e : null
}

// Store an answer read in session `ep`; refused (false) when that session has ended
export function store(path, data, at, ep) {
  if (ep !== epoch) return false
  entries.set(path, { data, at, epoch: ep })
  return true
}
