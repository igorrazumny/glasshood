// File: frontend/src/utils/canvasParts.test.js
// Purpose: REQ-GHA-023 — the count matches the canvas; the VM carries the attestation badge
// Run: node frontend/src/utils/canvasParts.test.js

import assert from 'node:assert/strict'
import { canvasNodes, statsSummary, attestationBadge, nearestSide, groupAttestationBadge, statsNodes, worstStatus, fitViewBox, anchorPoint, edgeStyle, boxSizes, isSpacer, connectionEdge, nestedChildIds, flowAnchors, elbowPath, routeEdge, pathD, labelPoint, placedPosition } from './canvasParts.js'

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

test('the opening view covers every group, padded', () => {
  assert.deepEqual(fitViewBox([{ x: 0, y: 0, w: 100, h: 50 }, { x: 300, y: 200, w: 100, h: 100 }], 10),
    { x: -10, y: -40, w: 420, h: 350 })
  assert.equal(fitViewBox([]), null)
})

test('edges attach at the facing side of a box: in on the left, out on the right', () => {
  const boxes = { app: { hw: 60, hh: 10 } }
  assert.deepEqual(anchorPoint('app', { x: 500, y: 100 }, { x: 200, y: 110 }, boxes), { x: 440, y: 100 })
  assert.deepEqual(anchorPoint('app', { x: 500, y: 100 }, { x: 900, y: 80 }, boxes), { x: 560, y: 100 })
  assert.deepEqual(anchorPoint('__grp_x_L', { x: 1, y: 2 }, { x: 9, y: 9 }, boxes), { x: 1, y: 2 })
})

test('box sizes cover nested children, narrower at each level', () => {
  const b = boxSizes([{ id: 'vm', children: [{ id: 'c', children: [{ id: 'app' }] }] }],
    { nodeW: 140, nodeHeight: () => 100, childHeight: () => 20, childPad: 8 })
  assert.deepEqual(b, { vm: { hw: 70, hh: 50 }, c: { hw: 62, hh: 10 }, app: { hw: 54, hh: 10 } })
})

test('flow lines are solid arrows; configuration lines thin and labelled', () => {
  assert.equal(edgeStyle({}).arrow, true)
  assert.equal(edgeStyle({}).dash, 'none')
  assert.equal(edgeStyle({ style: 'thin' }).showLabel, true)
  assert.equal(edgeStyle({ style: 'thin' }).arrow, false)
  assert.equal(edgeStyle({ style: 'dashed' }).dash, '6 4')
})

test('spacer cells and styled connections from the manifest', () => {
  assert.equal(isSpacer('_e1'), true)
  assert.equal(isSpacer('cv-ip'), false)
  assert.deepEqual(connectionEdge('a', 'b'), { source: 'a', target: 'b', label: '', status: 'healthy', style: 'default' })
  assert.deepEqual(connectionEdge('a', { to: '@vms', style: 'thin', label: 'runs as' }),
    { source: 'a', target: '@vms', label: 'runs as', status: 'healthy', style: 'thin' })
})

test('flow lines use the side middles even when the other end is far above or below', () => {
  const boxes = { app: { hw: 54, hh: 14 } }
  // firewall to the left and 150 above: still the app's left middle, never its top
  assert.deepEqual(anchorPoint('app', { x: 1318, y: 382 }, { x: 1100, y: 230 }, boxes, true), { x: 1264, y: 382 })
  // AI group to the right and far below: the app's right middle, never its bottom
  assert.deepEqual(anchorPoint('app', { x: 1318, y: 382 }, { x: 1700, y: 900 }, boxes, true), { x: 1372, y: 382 })
})

test('nested boxes are known, so their lines are drawn above the VM box', () => {
  const ids = nestedChildIds([{ id: 'vm', children: [{ id: 'c', children: [{ id: 'app' }] }] }, { id: 'ip' }])
  assert.deepEqual([...ids].sort(), ['app', 'c'])
})

test('a step below joins bottom-middle to top-middle; a step beside joins side middles', () => {
  const boxes = { ip: { hw: 70, hh: 25 }, rule: { hw: 70, hh: 25 }, vis: { hw: 70, hh: 25 } }
  const down = flowAnchors('ip', 'rule', { x: 500, y: 100 }, { x: 500, y: 180 }, boxes)
  assert.deepEqual(down, { from: { x: 500, y: 125 }, to: { x: 500, y: 155 }, axis: 'v' })
  const beside = flowAnchors('vis', 'ip', { x: 200, y: 100 }, { x: 500, y: 100 }, boxes)
  assert.deepEqual(beside, { from: { x: 270, y: 100 }, to: { x: 430, y: 100 }, axis: 'h' })
})

test('an axis hint steers a branch; a nested app is always entered from the side', () => {
  const boxes = { ip: { hw: 70, hh: 25 }, http: { hw: 70, hh: 25 }, app: { hw: 54, hh: 14 } }
  const branch = flowAnchors('ip', 'http', { x: 500, y: 100 }, { x: 300, y: 180 }, boxes, null, 'v')
  assert.deepEqual(branch.from, { x: 500, y: 125 })
  assert.deepEqual(branch.to, { x: 300, y: 155 })
  const app = flowAnchors('fw', 'app', { x: 900, y: 500 }, { x: 1000, y: 200 }, boxes, new Set(['app']), 'v')
  assert.equal(app.axis, 'h')
  assert.deepEqual(app.to, { x: 946, y: 200 })
})

test('lines are straight when aligned, right-angled otherwise, never slanted', () => {
  assert.equal(elbowPath({ x: 0, y: 10 }, { x: 100, y: 10 }, 'h'), 'M 0 10 L 100 10')
  assert.equal(elbowPath({ x: 0, y: 10 }, { x: 100, y: 50 }, 'h'), 'M 0 10 H 50 V 50 H 100')
  assert.equal(elbowPath({ x: 5, y: 0 }, { x: 5, y: 80 }, 'v'), 'M 5 0 L 5 80')
  assert.equal(elbowPath({ x: 5, y: 0 }, { x: 65, y: 80 }, 'v'), 'M 5 0 V 40 H 65 V 80')
})

test('a connection may carry an axis hint; anything else is ignored', () => {
  assert.equal(connectionEdge('a', { to: 'b', axis: 'v' }).axis, 'v')
  assert.equal(connectionEdge('a', { to: 'b', axis: 'diagonal' }).axis, undefined)
})

const B = (x, y, hw = 70, hh = 25) => ({ x, y, hw, hh })

test('aligned boxes get a straight line', () => {
  const r = routeEdge({ src: { box: B(500, 200) }, tgt: { box: B(500, 280) } })
  assert.equal(r.bends, 0)
  assert.deepEqual(r.pts, [{ x: 500, y: 225 }, { x: 500, y: 255 }])
  const h = routeEdge({ src: { box: B(500, 520) }, tgt: { box: B(880, 520) } })
  assert.equal(h.bends, 0)
})

test('offset boxes get one bend where one is enough', () => {
  const r = routeEdge({ src: { box: B(500, 200) }, tgt: { box: B(900, 500) } })
  assert.equal(r.bends, 1)
})

test('a line into a group lands level with its source, so it stays straight', () => {
  const group = { box: B(1560, 535, 90, 145), isGroup: true }
  const r = routeEdge({ src: { box: B(1080, 520, 54, 14) }, tgt: group, srcSides: ['L', 'R'] })
  assert.equal(r.bends, 0)
  assert.equal(r.pts[1].y, 520)
})

test('a box in the way is avoided even at the cost of a bend', () => {
  const blocker = B(700, 520)
  const r = routeEdge({ src: { box: B(500, 520) }, tgt: { box: B(900, 520) }, obstacles: [blocker] })
  assert.equal(r.hits, 0)
  assert.ok(r.bends >= 1)
})

test('a nested app keeps its side ports', () => {
  const r = routeEdge({ src: { box: B(880, 400) }, tgt: { box: B(1080, 520, 54, 14) }, tgtSides: ['L', 'R'] })
  assert.equal(r.pts[r.pts.length - 1].x, 1026)
})

test('path and label helpers', () => {
  assert.equal(pathD([{ x: 0, y: 0 }, { x: 10, y: 0 }]), 'M 0 0 L 10 0')
  assert.deepEqual(labelPoint([{ x: 0, y: 0 }, { x: 0, y: 10 }, { x: 100, y: 10 }]), { x: 50, y: 10 })
})

test('a manifest pos places a box; further VMs stack below the group pos', () => {
  assert.deepEqual(placedPosition({ pos: { x: 5, y: 6 } }, {}, 0, {}), { x: 5, y: 6 })
  const g = { dynamic: true, pos: { x: 1080, y: 509 } }
  assert.deepEqual(placedPosition({}, g, 0, {}, () => 162), { x: 1080, y: 509 })
  assert.deepEqual(placedPosition({}, g, 1, {}, () => 162), { x: 1080, y: 691 })
  assert.equal(placedPosition({}, {}, 0, {}), null)
})

test('selected canvas counts and status ignore the portfolio status and other systems', () => {
  const portfolio = { overall_status: 'healthy', nodes: [{ id: 'own', status: 'healthy' }] }
  const summary = statsSummary(portfolio, [{ id: 'external-a', status: 'error' }, { id: 'external-b', status: 'healthy' }])
  assert.deepEqual(summary, { total: 2, byStatus: { error: 1, healthy: 1 }, overall: 'error' })
  assert.equal(statsSummary(portfolio, [{ id: 'own', status: 'healthy' }]).overall, 'healthy')
})

test('empty and unassessed selected canvases do not become healthy', () => {
  const portfolio = { overall_status: 'healthy', nodes: [{ id: 'other', status: 'healthy' }] }
  assert.equal(statsSummary(portfolio, []), null)
  assert.equal(statsSummary(portfolio, [{ id: 'unread', status: 'not checked' }]).overall, 'not checked')
  assert.equal(statsSummary(portfolio, [{ id: 'idle', status: 'idle' }]).overall, 'idle')
})

if (failed) { console.error(`${failed} failed`); process.exit(1) }
