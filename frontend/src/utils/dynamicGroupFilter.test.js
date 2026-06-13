// File: frontend/src/utils/dynamicGroupFilter.test.js
// Purpose: Test that dynamic VM groups only include VMs from their own MIG parent (REQ-205)
// Run: node frontend/src/utils/dynamicGroupFilter.test.js

import assert from 'node:assert/strict'
import { filterVMsForGroup } from './manifestLayout.js'

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

console.log('Dynamic VM group filter tests (REQ-205) — imports production code:')

test('platform VMs only include platform MIG children', () => {
  const nodes = [
    { id: 'vm-example-mig-7qhq', metrics: { _parent: 'mig-platform' } },
    { id: 'vm-example-mig-04x3', metrics: { _parent: 'mig-platform' } },
    { id: 'vm-coldvault-mig-3q0c', metrics: { _parent: 'cv-mig' } },
    { id: 'vm-coldvault-mig-c3gp', metrics: { _parent: 'cv-mig' } },
  ]
  const result = filterVMsForGroup(nodes, 'mig-platform')
  assert.equal(result.length, 2)
  assert.ok(result.every(n => n.metrics._parent === 'mig-platform'))
})

test('coldvault VMs only include coldvault MIG children', () => {
  const nodes = [
    { id: 'vm-example-mig-7qhq', metrics: { _parent: 'mig-platform' } },
    { id: 'vm-coldvault-mig-3q0c', metrics: { _parent: 'cv-mig' } },
  ]
  const result = filterVMsForGroup(nodes, 'cv-mig')
  assert.equal(result.length, 1)
  assert.equal(result[0].id, 'vm-coldvault-mig-3q0c')
})

test('VMs without _parent are excluded', () => {
  const nodes = [
    { id: 'vm-orphan-123', metrics: {} },
    { id: 'vm-example-mig-7qhq', metrics: { _parent: 'mig-platform' } },
  ]
  const result = filterVMsForGroup(nodes, 'mig-platform')
  assert.equal(result.length, 1)
})

test('non-VM nodes are excluded even with matching _parent', () => {
  const nodes = [
    { id: 'lb-platform', metrics: { _parent: 'mig-platform' } },
    { id: 'vm-example-mig-7qhq', metrics: { _parent: 'mig-platform' } },
  ]
  const result = filterVMsForGroup(nodes, 'mig-platform')
  assert.equal(result.length, 1)
  assert.equal(result[0].id, 'vm-example-mig-7qhq')
})

test('empty topology returns empty', () => {
  assert.equal(filterVMsForGroup([], 'mig-platform').length, 0)
  assert.equal(filterVMsForGroup(null, 'mig-platform').length, 0)
})

console.log('\nDone.')
