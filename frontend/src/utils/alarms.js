// File: frontend/src/utils/alarms.js
// Purpose: Plain lines for the alarm list — current, resolved, not checked (REQ-GHA-027)

import { clock, clockRange } from './time.js'

// REQ-GHA-030: the reader's own time zone, named
const hhmm = iso => clock(iso)

// "since 10:46 CET · last seen 11:02 CET" for an active alarm
export function alarmWhen(alert) {
  const since = hhmm(alert.first_seen || alert.triggered_at)
  const last = hhmm(alert.last_seen)
  return last && last !== since ? `since ${since} · last seen ${last}` : `since ${since}`
}

// "10:46–11:02 CET" for a resolved alarm
export function resolvedWhen(alert) {
  return clockRange(alert.first_seen || alert.triggered_at, alert.ended_at)
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

// REQ-GHA-028: "example" or "observation" for alarms shown on the demo that are not
// yet trusted; empty for a real alarm
export function alarmKindLabel(alert) {
  return alert.kind === 'example' || alert.kind === 'observation' ? alert.kind : ''
}

// Critical first, then warning; at equal severity real alarms before examples
export function sortAlarms(alerts) {
  const order = { critical: 0, warning: 1, info: 2 }
  return [...(alerts || [])].sort((a, b) =>
    ((order[a.severity] ?? 3) - (order[b.severity] ?? 3)) ||
    ((alarmKindLabel(a) ? 1 : 0) - (alarmKindLabel(b) ? 1 : 0)))
}

// REQ-GHA-029: the tag in front of an alarm's title ("AI review" for one the AI found)
export function alarmTag(alert) {
  return alert.kind === 'ai' ? 'AI review' : alarmKindLabel(alert)
}

// How the server finds this alarm: its group and part (the rule id for older alarms)
export function alarmRef(alert) {
  return { group: alert.group || alert.rule_id, node_id: alert.node_id || null }
}

// The report's "ongoing or once" in plain words
export function patternLabel(pattern) {
  return { ongoing: 'Still going on', once: 'Happened once', recurring: 'Keeps coming back' }[pattern] || 'Not clear yet'
}

// The server's reason from an apiFetch error ("409: {"detail":"..."}"), else the message
export function errorText(err) {
  const m = String(err?.message || err || '')
  try { return JSON.parse(m.slice(m.indexOf('{'))).detail || m } catch { return m }
}
