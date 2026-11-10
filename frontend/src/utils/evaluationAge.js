// File: frontend/src/utils/evaluationAge.js
// Purpose: REQ-GHA-050 — when an evaluation was made, and whether it is out of date.

import { clock } from './time.js'

// Clause 2 (amended): rounds start 3 hours after the previous one ends; the extra hour keeps a normal cycle unmarked
export const OUT_OF_DATE_MS = 4 * 3600e3

const dayKey = (ms, timeZone) => new Intl.DateTimeFormat('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(ms))

// Clause 1: the time alone only today; "yesterday 15:35 CET"; "3 Nov, 15:35 CET"
// (the year is added only when it is not the current one)
export function evaluatedWhen(atMs, nowMs, { timeZone } = {}) {
  if (!atMs) return ''
  const t = clock(atMs, { timeZone })
  if (dayKey(atMs, timeZone) === dayKey(nowMs, timeZone)) return t
  // yesterday is the first day met going back from now, so a 23- or 25-hour day still has one
  const today = dayKey(nowMs, timeZone)
  let back = nowMs
  while (dayKey(back, timeZone) === today) back -= 3600e3
  if (dayKey(atMs, timeZone) === dayKey(back, timeZone)) return `yesterday ${t}`
  const sameYear = new Date(atMs).getFullYear() === new Date(nowMs).getFullYear()
  const date = new Intl.DateTimeFormat('en-GB', { timeZone, day: 'numeric', month: 'short', ...(sameYear ? {} : { year: 'numeric' }) }).format(new Date(atMs))
  return `${date}, ${t}`
}

function ageWords(ms) {
  const h = Math.floor(ms / 3600e3)
  if (h < 24) return `${h} hour${h === 1 ? '' : 's'} old`
  const d = Math.floor(h / 24)
  return `${d} day${d === 1 ? '' : 's'} old`
}

// Clauses 2-4: null while current; otherwise the amber mark and the one true line about the new one.
// state: 'running' | 'failed' | anything else (waiting)
export function outOfDate(atMs, nowMs, state) {
  if (!atMs || nowMs - atMs <= OUT_OF_DATE_MS) return null
  const next = state === 'running' ? 'A new evaluation is running.'
    : state === 'failed' ? 'The new evaluation failed; it will be tried again.'
      : 'Waiting for a new evaluation.'
  return { mark: `Out of date · ${ageWords(nowMs - atMs)}`, next }
}

// What a record's job says about the next evaluation; a fresh check after waking counts as running
export function nextState(about, measuring = false) {
  const s = about?.job?.status
  if (s === 'running') return 'running'
  if (s === 'retrying' || s === 'failed' || about?.error || about?.update_failed) return 'failed'
  return measuring ? 'running' : 'waiting'
}
