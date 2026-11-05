// File: frontend/src/utils/overview.js
// Purpose: REQ-GHA-024 — how an AI overview's time, model and spend read on screen.

export function ago(tsSeconds, now = Date.now()) {
  const s = Math.max(0, Math.round(now / 1000 - tsSeconds))
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`
  return `${Math.floor(s / 86400)} d ago`
}

export function overviewStamp(o, now = Date.now()) {
  if (!o?.analyzed_at) return o?.model ? `Not written yet · ${o.model}` : 'Not written yet'
  const t = new Date(o.analyzed_at * 1000)
  const hhmm = t.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  return `Updated ${hhmm}, ${ago(o.analyzed_at, now)}${o.model ? ` · ${o.model}` : ''}`
}

export function spendLine(sp) {
  const base = `Today: ${sp.calls} model calls, about $${Number(sp.cost_usd || 0).toFixed(2)} (cap ${sp.daily_call_cap} calls)`
  return sp.capped ? `${base} — daily cap reached, no more overviews today` : base
}
