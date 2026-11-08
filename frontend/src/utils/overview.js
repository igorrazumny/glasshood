// File: frontend/src/utils/overview.js
// Purpose: REQ-GHA-024 — how an AI overview's time and spend read on screen. The model is
// not named: GlassHood uses whichever model suits (Igor, 2026-11-06).

import { clock } from './time.js'

export function ago(tsSeconds, now = Date.now()) {
  const s = Math.max(0, Math.round(now / 1000 - tsSeconds))
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`
  return `${Math.floor(s / 86400)} d ago`
}

export function overviewStamp(o, now = Date.now()) {
  if (!o?.analyzed_at) return 'Not evaluated yet'
  return `Evaluated ${clock(o.analyzed_at * 1000)}, ${ago(o.analyzed_at, now)}`
}

export function spendLine(sp) {
  const base = `Today: ${sp.calls} model calls, about $${Number(sp.cost_usd || 0).toFixed(2)} (cap ${sp.daily_call_cap} calls)`
  if (sp.usage_read === false && sp.read_error) return `${base} — ${sp.read_error}; no new overviews until it can be read`
  return sp.capped ? `${base} — daily cap reached, no more overviews today` : base
}

// Clause 7: an overview older than its schedule is stale — judged by its age now, not only by
// the flag it carried when it was fetched.
export function isStale(o, now = Date.now()) {
  if (!o?.analyzed_at) return false
  const interval = o.interval_s || 3 * 3600
  return !!o.stale || (now / 1000 - o.analyzed_at) > interval
}
