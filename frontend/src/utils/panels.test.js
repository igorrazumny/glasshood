// File: frontend/src/utils/panels.test.js
// Purpose: REQ-GHA-033 — panel widths stay readable, leave the landscape visible, and are remembered
// Run: node frontend/src/utils/panels.test.js

import assert from 'node:assert/strict'
import { PANELS, MIN_LANDSCAPE, OVERLAY_BELOW, landscapeInsets, clampWidth, fitPanels, loadPanel, savePanel, dragWidth } from './panels.js'

let failed = 0
function test(name, fn) {
  try { fn(); console.log(`  ✅ ${name}`) } catch (e) { failed++; console.error(`  ❌ ${name}\n     ${e.message}`) }
}

function memory() {
  const m = new Map()
  return { getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)) }
}

test('a width is never below the readable minimum', () => {
  assert.equal(clampWidth('right', 50, 1440), PANELS.right.min)
  assert.equal(clampWidth('left', 10, 1440), PANELS.left.min)
})

test('one open panel always leaves the landscape its room', () => {
  assert.equal(clampWidth('right', 2000, 1000), 1000 - MIN_LANDSCAPE - 16)
  assert.equal(clampWidth('right', 2000, 2560), PANELS.right.max)
})

test('two wide panels on a 1000px window still leave the landscape visible', () => {
  for (const vw of [1000, 1024, 1280]) {
    const w = fitPanels({ left: { open: true, width: 500 }, right: { open: true, width: 500 } }, vw)
    const landscape = vw - (w.left + 8) - (w.right + 8)
    assert.ok(landscape >= MIN_LANDSCAPE, `${vw}px: landscape ${landscape}`)
    assert.ok(w.left >= PANELS.left.min && w.right >= PANELS.right.min)
  }
})

test('saved wide panels are fitted again after the window shrinks', () => {
  const s = memory()
  savePanel('left', { open: true, width: 520 }, s)
  savePanel('right', { open: true, width: 760 }, s)
  const w = fitPanels({ left: loadPanel('left', s), right: loadPanel('right', s) }, 1024)
  assert.ok(1024 - w.left - w.right - 16 >= MIN_LANDSCAPE)
})

test('a closed panel takes no room and gives it to the other', () => {
  const w = fitPanels({ left: { open: false, width: 300 }, right: { open: true, width: 760 } }, 1440)
  assert.equal(w.left, 0)
  assert.equal(w.right, PANELS.right.max)
})

test('on a phone the panels keep their minimum and open over the landscape', () => {
  const w = fitPanels({ left: { open: true, width: 400 }, right: { open: true, width: 400 } }, 390)
  assert.deepEqual(w, { left: PANELS.left.min, right: PANELS.right.min })
})

test('a width inside the limits is kept', () => {
  assert.equal(clampWidth('right', 450, 1440), 450)
})

test('dragging the right edge left widens the right panel', () => {
  assert.equal(dragWidth('right', 1440 - 500, 1440), 500)
  assert.equal(dragWidth('right', 1440 - 300, 1440), 300)
})

test('dragging the left panel edge follows the pointer', () => {
  assert.equal(dragWidth('left', 300, 1440), 300)
})

test('open state and width are remembered', () => {
  const s = memory()
  savePanel('right', { open: false, width: 480 }, s)
  assert.deepEqual(loadPanel('right', s), { open: false, width: 480 })
})

test('nothing saved gives an open panel at the default width', () => {
  assert.deepEqual(loadPanel('left', memory()), { open: true, width: PANELS.left.width })
})

test('blocked or broken storage still gives a working panel', () => {
  const broken = { getItem: () => { throw new Error('blocked') }, setItem: () => { throw new Error('blocked') } }
  assert.deepEqual(loadPanel('right', broken), { open: true, width: PANELS.right.width })
  savePanel('right', { open: true, width: 400 }, broken)
  const s = memory(); s.setItem('glasshood.panel.left', '{not json')
  assert.deepEqual(loadPanel('left', s), { open: true, width: PANELS.left.width })
})

test('on a phone open panels lie over the landscape, which keeps the full width', () => {
  const w = fitPanels({ left: { open: true, width: 400 }, right: { open: true, width: 400 } }, 390)
  assert.deepEqual(landscapeInsets(w, 390), { left: 8, right: 8 })
})

test('on a desktop the landscape is inset by each open pinned panel', () => {
  assert.deepEqual(landscapeInsets({ left: 240, right: 320 }, 1440), { left: 248, right: 328 })
  assert.deepEqual(landscapeInsets({ left: 0, right: 320 }, 1440), { left: 8, right: 328 })
  const w = fitPanels({ left: { open: true, width: 999 }, right: { open: true, width: 999 } }, OVERLAY_BELOW)
  const i = landscapeInsets(w, OVERLAY_BELOW)
  assert.ok(OVERLAY_BELOW - i.left - i.right >= MIN_LANDSCAPE)
})

test('storage that throws when merely touched still gives a working panel', () => {
  const desc = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, get() { throw new Error('SecurityError') } })
  try {
    assert.deepEqual(loadPanel('right'), { open: true, width: PANELS.right.width })
    savePanel('right', { open: true, width: 400 })
  } finally {
    if (desc) Object.defineProperty(globalThis, 'localStorage', desc); else delete globalThis.localStorage
  }
})

if (failed) { console.error(`${failed} failed`); process.exit(1) }
