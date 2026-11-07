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

// The landscape always keeps at least this much width beside the open panels.
export const MIN_LANDSCAPE = 360
const GUTTERS = 16

// Never less than the readable minimum; never so wide that the landscape gets
// less than MIN_LANDSCAPE next to this panel and the other open panel
// (otherWidth, 0 when the other panel is closed). When even the minimum does not
// fit (a phone), the panel keeps its minimum and opens over the landscape.
export function clampWidth(side, width, viewport = 1440, otherWidth = 0) {
  const p = PANELS[side]
  const room = viewport - otherWidth - MIN_LANDSCAPE - GUTTERS
  const max = Math.max(p.min, Math.min(p.max, room))
  const w = Number.isFinite(width) ? Math.round(width) : p.width
  return Math.min(max, Math.max(p.min, w))
}

// Widths of both panels for this window. The right panel (overview and alarms)
// is fitted first against the left panel's minimum, then the left panel gets the
// room that is left, so together they always leave the landscape visible.
export function fitPanels({ left, right }, viewport) {
  const r = right.open ? clampWidth('right', right.width, viewport, left.open ? PANELS.left.min : 0) : 0
  const l = left.open ? clampWidth('left', left.width, viewport, r) : 0
  return { left: l, right: r }
}

// Below this width the two panels and the landscape do not fit side by side
// (a phone): open panels then lie over the landscape instead of pushing it aside.
export const OVERLAY_BELOW = PANELS.left.min + PANELS.right.min + MIN_LANDSCAPE + GUTTERS

// How far the landscape is inset from each side: the width of each open, pinned
// panel plus a gutter, or just the gutter when panels lie over it.
export function landscapeInsets({ left, right }, viewport) {
  if (viewport < OVERLAY_BELOW) return { left: 8, right: 8 }
  return { left: left ? left + 8 : 8, right: right ? right + 8 : 8 }
}

const key = side => `glasshood.panel.${side}`

// Saved state, or the default when nothing is saved or storage is blocked
export function loadPanel(side, storage) {
  const fallback = { open: true, width: PANELS[side].width }
  try {
    // Resolved inside try: a browser policy can throw on merely touching localStorage
    storage = storage ?? globalThis.localStorage
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

export function savePanel(side, state, storage) {
  try {
    storage = storage ?? globalThis.localStorage
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
