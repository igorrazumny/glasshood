// File: frontend/src/utils/panels.test.js
// Purpose: REQ-GHA-033 — panel widths stay readable, leave the landscape visible, and are remembered
// Run: node frontend/src/utils/panels.test.js

import assert from 'node:assert/strict'
import { PANELS, clampWidth, loadPanel, savePanel, dragWidth } from './panels.js'

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

test('a width never takes more than half the window', () => {
  assert.equal(clampWidth('right', 2000, 1200), 600)
  assert.equal(clampWidth('right', 2000, 2560), PANELS.right.max)
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

if (failed) { console.error(`${failed} failed`); process.exit(1) }
