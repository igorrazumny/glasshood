// File: frontend/src/utils/panels.js
// Purpose: REQ-GHA-033 — side panel widths and open/closed state.
// A width is kept between a readable minimum and a maximum that leaves the
// landscape visible; both are remembered in this browser between visits.

// The panels start under the top bar (StatusHeader, h-16 = 64px). They used to start
// at 40px, from before the bar was made taller, so the bar covered their hide controls.
export const PANEL_TOP = 64

export const PANELS = {
  left: { min: 200, max: 520, width: 240 },
  right: { min: 280, max: 760, width: 320 },
}

// Never less than the readable minimum; never so wide that the landscape
// gets less than about half the window.
export function clampWidth(side, width, viewport = 1440) {
  const p = PANELS[side]
  const max = Math.max(p.min, Math.min(p.max, Math.floor(viewport * 0.5)))
  const w = Number.isFinite(width) ? Math.round(width) : p.width
  return Math.min(max, Math.max(p.min, w))
}

const key = side => `glasshood.panel.${side}`

// Saved state, or the default when nothing is saved or storage is blocked
export function loadPanel(side, storage = globalThis.localStorage) {
  const fallback = { open: true, width: PANELS[side].width }
  try {
    const saved = JSON.parse(storage?.getItem(key(side)) || 'null')
    if (!saved || typeof saved !== 'object') return fallback
    return {
      open: saved.open !== false,
      width: Number.isFinite(saved.width) ? saved.width : fallback.width,
    }
  } catch {
    return fallback
  }
}

export function savePanel(side, state, storage = globalThis.localStorage) {
  try {
    storage?.setItem(key(side), JSON.stringify({ open: !!state.open, width: state.width }))
  } catch { /* private window or blocked storage: the panel still works, just not remembered */ }
}

// Width while dragging the panel's inner edge. The left panel's edge is its
// right side, so its width is the pointer's x; the right panel's edge is its
// left side, so its width is the distance from the pointer to the window edge.
export function dragWidth(side, clientX, viewport) {
  const raw = side === 'left' ? clientX : viewport - clientX
  return clampWidth(side, raw, viewport)
}
