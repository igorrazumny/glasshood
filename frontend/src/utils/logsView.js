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

const key = e => `${e.timestamp}|${e.severity}|${e.message}`
const when = e => { const t = Date.parse(e.timestamp); return Number.isNaN(t) ? 0 : t }

// clause 13: nothing loaded is removed; the lines are kept oldest first, newest at the bottom
export function mergeEntries(existing, incoming) {
  const have = existing || []
  const seen = new Set(have.map(key))
  const added = (incoming || []).filter(e => e && e.timestamp !== undefined && !seen.has(key(e)))
  if (!added.length) return have
  return [...have, ...added].sort((a, b) => when(a) - when(b))
}
