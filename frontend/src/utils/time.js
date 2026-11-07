// File: frontend/src/utils/time.js
// Purpose: REQ-GHA-030 — every time on screen is in the reader's own time zone (the device's)
// and carries that zone's short name, for example "12:53 CET". 24-hour clock everywhere.
// timeZone is only passed by tests; the screen always uses the device's zone.

const fmt = (opts, timeZone) => new Intl.DateTimeFormat('en-GB', { hourCycle: 'h23', timeZone, ...opts })

// Accepts a Date, an ISO string or milliseconds; '' / null / invalid give null
function toDate(value) {
  if (value == null || value === '') return null
  const d = value instanceof Date ? value : new Date(value)
  return Number.isNaN(d.getTime()) ? null : d
}

export function zoneName(value, timeZone) {
  const d = toDate(value)
  if (!d) return ''
  return fmt({ timeZoneName: 'short' }, timeZone).formatToParts(d).find(p => p.type === 'timeZoneName')?.value || ''
}

// "12:53 CET"
export function clock(value, { timeZone, seconds = false } = {}) {
  const d = toDate(value)
  if (!d) return ''
  const opts = { hour: '2-digit', minute: '2-digit', ...(seconds ? { second: '2-digit' } : {}) }
  return `${fmt(opts, timeZone).format(d)} ${zoneName(d, timeZone)}`
}

// "7 Nov 2026, 12:53 CET"
export function dateTime(value, { timeZone } = {}) {
  const d = toDate(value)
  if (!d) return ''
  return `${fmt({ day: 'numeric', month: 'short', year: 'numeric' }, timeZone).format(d)}, ${clock(d, { timeZone })}`
}

// "09:05–09:40 CET" (one zone name when both ends share it)
export function clockRange(from, to, { timeZone } = {}) {
  const a = clock(from, { timeZone }), b = clock(to, { timeZone })
  if (!a || !b) return a || b
  const za = zoneName(from, timeZone)
  return za === zoneName(to, timeZone) ? `${a.slice(0, -za.length - 1)}–${b}` : `${a}–${b}`
}
