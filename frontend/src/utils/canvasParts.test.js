// File: frontend/src/utils/canvasParts.test.js
// Purpose: REQ-GHA-023 — the count matches the canvas; the VM carries the attestation badge
// Run: node frontend/src/utils/canvasParts.test.js

import assert from 'node:assert/strict'
import { canvasNodes, attestationBadge, nearestSide, groupAttestationBadge, statsNodes, worstStatus } from './canvasParts.js'

let failed = 0
function test(name, fn) {
  try { fn(); console.log(`  ✅ ${name}`) } catch (e) { failed++; console.error(`  ❌ ${name}\n     ${e.message}`) }
}

const layout = {
  manifestNodes: [
    { id: 'cv-ip', status: 'healthy' },
    { id: 'vm-a', status: 'healthy', children: [
      { id: 'vm-a-docker', status: 'healthy', children: [{ id: 'vm-a-api', status: 'healthy' }] },
    ] },
    { id: 'cv-openai', status: 'not checked' },
  ],
  groups: [{ parent: 'cv-mig' }, { parent: null }],
}
const topo = [
  { id: 'cv-mig', status: 'healthy' },
  { id: 'gpu_h100_spot', status: 'offline' },   // in the topology, not on the canvas
  { id: 'fr-discovered', status: 'healthy' },   // discovered asset, not drawn
]

test('counts placed nodes, nested children and dynamic-group parents', () => {
  const ids = canvasNodes(layout, topo).map(n => n.id)
  assert.deepEqual(ids.sort(), ['cv-ip', 'cv-mig', 'cv-openai', 'vm-a', 'vm-a-api', 'vm-a-docker'])
})

test('topology nodes not drawn are not counted', () => {
  const ids = canvasNodes(layout, topo).map(n => n.id)
  assert.ok(!ids.includes('gpu_h100_spot') && !ids.includes('fr-discovered'))
})

test('statuses come along, including not checked', () => {
  const byId = Object.fromEntries(canvasNodes(layout, topo).map(n => [n.id, n.status]))
  assert.equal(byId['cv-openai'], 'not checked')
  assert.equal(byId['cv-mig'], 'healthy')
})

test('a node drawn twice is counted once', () => {
  const twice = { manifestNodes: [{ id: 'x', status: 'healthy' }, { id: 'x', status: 'healthy' }], groups: [] }
  assert.equal(canvasNodes(twice, []).length, 1)
})

test('no layout gives no override', () => {
  assert.equal(canvasNodes(null, topo), null)
})

test('badge only when an attestation result exists', () => {
  assert.equal(attestationBadge({ metrics: {} }), '')
  assert.equal(attestationBadge({}), '')
  assert.equal(attestationBadge({ metrics: { attested: 1 } }), ' · SEV-SNP attested ✓')
  assert.equal(attestationBadge({ metrics: { attested: 0 } }), ' · not attested')
})

const box = { x: 100, y: 100, w: 200, h: 100 }   // centre (200, 150)

test('edges meet the side of a group facing the other end', () => {
  assert.deepEqual(nearestSide(box, { x: 0, y: 150 }), { side: 'left', point: { x: 100, y: 150 } })
  assert.deepEqual(nearestSide(box, { x: 500, y: 140 }), { side: 'right', point: { x: 300, y: 150 } })
  assert.deepEqual(nearestSide(box, { x: 210, y: 400 }), { side: 'bottom', point: { x: 200, y: 200 } })
  assert.deepEqual(nearestSide(box, { x: 190, y: -50 }), { side: 'top', point: { x: 200, y: 100 } })
})

test('without the other end, the left side as before', () => {
  assert.equal(nearestSide(box, undefined).side, 'left')
})

test('group carries the endpoint result only when several VMs share the endpoint', () => {
  const mig = { id: 'mig', metrics: { endpoint_attested: 1 } }
  const vm = (id) => ({ id, metrics: { _parent: 'mig' } })
  assert.equal(groupAttestationBadge('mig', [mig, vm('a')]), '')
  assert.equal(groupAttestationBadge('mig', [mig, vm('a'), vm('b')]), ' · endpoint SEV-SNP attested ✓ (VM not identified)')
  assert.equal(groupAttestationBadge('mig', [{ id: 'mig', metrics: { endpoint_attested: 0 } }, vm('a'), vm('b')]), ' · endpoint not attested')
  assert.equal(groupAttestationBadge('mig', [{ id: 'mig', metrics: {} }, vm('a'), vm('b')]), '')
})

test('manifests before topology: nothing to count yet, no crash', () => {
  assert.equal(statsNodes(null, [{ id: 'cv-ip', status: 'not monitored' }]), null)
  assert.equal(statsNodes(undefined, null), null)
})

test('canvas wins over topology once both exist; topology alone otherwise', () => {
  const topo = { nodes: [{ id: 'a' }, { id: 'b' }] }
  assert.deepEqual(statsNodes(topo, [{ id: 'a' }]), [{ id: 'a' }])
  assert.deepEqual(statsNodes(topo, null), topo.nodes)
  assert.equal(statsNodes({ nodes: [] }, null), null)
})

test('failed endpoint attestation turns a group of healthy VMs yellow', () => {
  assert.equal(worstStatus(['healthy', 'healthy', 'degraded']), 'degraded')  // two VMs + parent
})

test('a member error still beats a degraded parent; no-health statuses are ignored', () => {
  assert.equal(worstStatus(['error', 'healthy', 'degraded']), 'error')
  assert.equal(worstStatus(['not checked', 'healthy', null]), 'healthy')
  assert.equal(worstStatus(['not monitored']), null)
})

if (failed) { console.error(`${failed} failed`); process.exit(1) }
