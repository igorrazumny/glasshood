// File: frontend/src/utils/alarms.js
// Purpose: Plain lines for the alarm list — current, resolved, not checked (REQ-GHA-027)

// Local 24-hour time, independent of the browser's locale
const pad = n => String(n).padStart(2, '0')
const hhmm = iso => {
  if (!iso) return ''
  const d = new Date(iso)
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}

// "since 10:46 · last seen 11:02" for an active alarm
export function alarmWhen(alert) {
  const since = hhmm(alert.first_seen || alert.triggered_at)
  const last = hhmm(alert.last_seen)
  return last && last !== since ? `since ${since} · last seen ${last}` : `since ${since}`
}

// "10:46–11:02" for a resolved alarm
export function resolvedWhen(alert) {
  return `${hhmm(alert.first_seen || alert.triggered_at)}–${hhmm(alert.ended_at)}`
}

// The plain line a reader sees; the technical message is the fallback only
export function alarmTitle(alert) {
  return alert.title || alert.message || ''
}

// Short names of the rules that had no data, each once; a name counts as checked
// when any rule with that name was checked (e.g. the warning and critical memory rules).
export function notCheckedNames(rules) {
  const checked = new Set((rules || []).filter(r => r.checked).map(r => r.name))
  return [...new Set((rules || []).filter(r => !r.checked && !checked.has(r.name)).map(r => r.name))]
}
