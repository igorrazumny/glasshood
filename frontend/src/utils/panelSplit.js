// File: frontend/src/utils/panelSplit.js
// Purpose: REQ-GHA-046 clause 14: the review/alerts boundary, kept within reach of both areas.
export const DEFAULT_SPLIT = 0.5
export function clampSplit(v) {
  const n = Number(v)
  return Number.isFinite(n) ? Math.min(0.85, Math.max(0.15, n)) : DEFAULT_SPLIT
}

// apiFetch hands back the parsed answer
export async function loadSplit(api) {
  const d = await api('/api/preferences/right-panel')
  return d?.split != null ? clampSplit(d.split) : null
}
