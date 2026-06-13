// File: frontend/src/components/dragEventOrder.test.js
// Purpose: Test that group/node drag handlers prevent SVG panning (REQ-104)
// Run: node frontend/src/components/dragEventOrder.test.js

import assert from 'node:assert/strict'

function test(name, fn) {
  try {
    fn()
    console.log(`  ✅ ${name}`)
  } catch (e) {
    console.error(`  ❌ ${name}`)
    console.error(`     ${e.message}`)
    process.exitCode = 1
  }
}

// Simulate the refs used in TopologyMap
function createRefs() {
  return {
    isPanning: { current: false },
    draggingNode: { current: null },
    draggingGroup: { current: null },
  }
}

// Extract the SVG onMouseDown guard logic
function svgOnMouseDown(refs) {
  if (refs.draggingNode.current || refs.draggingGroup.current !== null) return false
  refs.isPanning.current = true
  return true // panning started
}

// Simulate group handler (fires BEFORE svgOnMouseDown via bubbling)
function groupOnMouseDown(refs, groupIdx) {
  refs.draggingGroup.current = groupIdx
  refs.draggingNode.current = null
  refs.isPanning.current = false
}

// Simulate node handler
function nodeOnMouseDown(refs, nodeId) {
  refs.draggingNode.current = nodeId
  refs.draggingGroup.current = null
  refs.isPanning.current = false
}

console.log('Drag event ordering tests (REQ-104):')

test('SVG mousedown enables panning when no drag active', () => {
  const refs = createRefs()
  const started = svgOnMouseDown(refs)
  assert.equal(started, true)
  assert.equal(refs.isPanning.current, true)
})

test('group mousedown prevents SVG from enabling panning', () => {
  const refs = createRefs()
  // Group handler fires first (bubbling order)
  groupOnMouseDown(refs, 0)
  assert.equal(refs.draggingGroup.current, 0)
  assert.equal(refs.isPanning.current, false)
  // SVG handler fires second
  const started = svgOnMouseDown(refs)
  assert.equal(started, false)
  assert.equal(refs.isPanning.current, false) // still false!
})

test('group index 0 is not falsy (null check, not truthy check)', () => {
  const refs = createRefs()
  groupOnMouseDown(refs, 0) // groupIdx = 0
  const started = svgOnMouseDown(refs)
  assert.equal(started, false) // must not pan — group 0 is valid
})

test('node mousedown prevents SVG from enabling panning', () => {
  const refs = createRefs()
  nodeOnMouseDown(refs, 'lb-platform')
  const started = svgOnMouseDown(refs)
  assert.equal(started, false)
  assert.equal(refs.isPanning.current, false)
})

test('SVG mousedown works after drag ends (refs cleared)', () => {
  const refs = createRefs()
  groupOnMouseDown(refs, 2)
  // Simulate drag end
  refs.draggingGroup.current = null
  refs.draggingNode.current = null
  refs.isPanning.current = false
  // Next click should pan
  const started = svgOnMouseDown(refs)
  assert.equal(started, true)
})

console.log('\nDone.')
