// File: frontend/src/utils/logsView.js
// Purpose: REQ-GHA-032 (amended 2026-11-09) — which boxes can open their logs, and how the log
// window keeps every line it has loaded while newer lines join at the bottom and earlier lines
// at the top.

export const PAGE = 300
export const EARLIER_EMPTY = 'No earlier lines in the last 7 days.'

// clause 11: a box shows View Logs only when GlassHood has a log source for it. A box whose
// landscape file says it has none gets no button; this is the one line its details show instead.
export function noLogsReason(node) {
  const logs = node?.monitoring_logs ?? node?.monitoring?.logs ?? null
  const first = Array.isArray(logs) ? logs[0] : null
  if (!first || first.source !== 'none') return null
  return first.reason || 'This part writes no logs GlassHood can read.'
}

// how many lines to ask for: one page plus those already held at the oldest moment, which come back
export function earlierLines(have) {
  return PAGE + (have || []).filter(e => e.timestamp === have[0].timestamp).length
}

// More lines at one moment than a request may carry cannot be paged through: step just before that
// moment, so older history stays reachable, and say that some lines there were not shown.
export const EARLIER_LIMIT = 2000
export function earlierRequest(have) {
  const lines = earlierLines(have)
  const ts = have[0].timestamp
  const ms = Date.parse(ts)
  // only a moment already holding a full request is skipped; below that, the largest request is tried first
  if (lines - PAGE < EARLIER_LIMIT || Number.isNaN(ms)) return { lines: Math.min(lines, EARLIER_LIMIT), before: ts, skipped: false }
  return { lines: PAGE, before: new Date(ms - 1).toISOString(), skipped: true }
}

const key = e => `${e.timestamp}|${e.severity}|${e.message}`
const when = e => { const t = Date.parse(e.timestamp); return Number.isNaN(t) ? 0 : t }

// clause 13: nothing loaded is removed; the lines are kept oldest first, newest at the bottom.
// Identical lines are separate occurrences: an answer adds only those beyond what is already held.
export function mergeEntries(existing, incoming) {
  const have = existing || []
  const held = new Map()
  for (const e of have) held.set(key(e), (held.get(key(e)) || 0) + 1)
  const added = (incoming || []).filter(e => {
    if (!e || e.timestamp === undefined) return false
    const left = held.get(key(e)) || 0
    if (left) { held.set(key(e), left - 1); return false }
    return true
  })
  if (!added.length) return have
  return [...have, ...added].sort((a, b) => when(a) - when(b))
}
