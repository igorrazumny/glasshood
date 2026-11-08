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
// REQ-GHA-045 clause 8: "15 min ago"; the exact times stay in alarmWhen, shown on hover
export function alarmAgo(alert, nowMs = Date.now()) {
  const at = new Date(alert.first_seen || alert.triggered_at).getTime()
  if (Number.isNaN(at)) return ''
  const min = Math.max(0, Math.round((nowMs - at) / 60000))
  if (min < 1) return 'just now'
  if (min < 60) return `${min} min ago`
  const h = Math.round(min / 60)
  return h < 24 ? `${h} h ago` : `${Math.round(h / 24)} d ago`
}

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
    ((alarmKindLabel(a) ? 1 : 0) - (alarmKindLabel(b) ? 1 : 0)) ||
    // REQ-GHA-027 (amended 2026-11-08): newest first within the same severity and kind
    String(b.first_seen || b.triggered_at || '').localeCompare(String(a.first_seen || a.triggered_at || '')))
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

// REQ-GHA-038: five severity levels, each its own list; examples apart
export const LEVELS = [
  { id: 'critical', label: 'Critical', dot: 'bg-red-500' },
  { id: 'high', label: 'High', dot: 'bg-orange-500' },
  { id: 'medium', label: 'Medium', dot: 'bg-yellow-400' },
  { id: 'low', label: 'Low', dot: 'bg-gray-400' },
  { id: 'info', label: 'Information', dot: 'bg-gray-300' },
  { id: 'example', label: 'Examples', dot: 'bg-gray-300' },
]

export function alarmLevel(alert) {
  if (alert?.kind === 'example') return 'example'
  if (alert?.kind === 'observation') return 'info'
  // a provider's maintenance arrives as info only when its own data shows no disruption
  if (alert?.severity === 'critical') return 'critical'
  if (alert?.severity === 'high') return 'high'
  if (alert?.severity === 'warning') return 'medium'
  if (alert?.severity === 'low') return 'low'
  return 'info'
}

// {level: [alerts newest first]} for the levels that have alarms; each list is ordered by
// time alone, so an alarm's original severity or kind does not reorder its list
const seen = a => String(a.first_seen || a.triggered_at || '')
export function alarmsByLevel(alerts) {
  const out = {}
  for (const a of alerts || []) (out[alarmLevel(a)] ||= []).push(a)
  for (const list of Object.values(out)) list.sort((a, b) => seen(b).localeCompare(seen(a)))
  return out
}

// Open at first: Critical and High; Medium unless Critical or High have alarms; the rest closed
export function defaultOpen(byLevel) {
  const urgent = (byLevel.critical?.length || 0) + (byLevel.high?.length || 0) > 0
  return { critical: true, high: true, medium: !urgent, low: false, info: false, example: false }
}
