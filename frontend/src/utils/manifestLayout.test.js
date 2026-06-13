// File: frontend/src/utils/manifestLayout.test.js
// Purpose: Tests for computeManifestLayout — grid placement, edge collection, edge cases
// Run: node frontend/src/utils/manifestLayout.test.js

import assert from 'node:assert/strict'
import { computeManifestLayout, buildParentNodeRecord } from './manifestLayout.js'

const nodes = [
  { id: 'a' }, { id: 'b' }, { id: 'c' },
  { id: 'd' }, { id: 'e' }, { id: 'f' },
]

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

console.log('manifestLayout tests:')

test('returns null for empty inputs', () => {
  assert.equal(computeManifestLayout([], []), null)
  assert.equal(computeManifestLayout(null, [{ groups: [] }]), null)
  assert.equal(computeManifestLayout(nodes, []), null)
  assert.equal(computeManifestLayout(nodes, null), null)
})

test('manifest nodes rendered even without topology match', () => {
  const manifests = [{
    groups: [{ name: 'g1', nodes: ['x', 'y', 'z'], order: 0, row: 0, col: 0 }],
    edges: [],
  }]
  const result = computeManifestLayout(nodes, manifests)
  assert.ok(result, 'manifest nodes are source of truth — always render')
  assert.ok(result.positions.x, 'x should have position')
  assert.equal(result.manifestNodes.length, 3, 'should create 3 manifest nodes')
})

test('grid placement: nodes positioned by row/col', () => {
  const manifests = [{
    groups: [
      { name: 'top-left', label: 'TL', style: 'default', order: 0, row: 0, col: 0, nodes: ['a', 'b'] },
      { name: 'top-right', label: 'TR', style: 'default', order: 1, row: 0, col: 1, nodes: ['c'] },
      { name: 'bot-left', label: 'BL', style: 'default', order: 2, row: 1, col: 0, nodes: ['d'] },
    ],
    edges: [],
  }]
  const result = computeManifestLayout(nodes, manifests)
  assert.ok(result, 'should return a result')
  assert.ok(result.positions.a, 'node a should have position')
  assert.ok(result.positions.c, 'node c should have position')
  assert.ok(result.positions.d, 'node d should have position')
  // top-right (col=1) should be to the right of top-left (col=0)
  assert.ok(result.positions.c.x > result.positions.a.x, 'col 1 should be right of col 0')
  // bot-left (row=1) should be below top-left (row=0)
  assert.ok(result.positions.d.y > result.positions.a.y, 'row 1 should be below row 0')
})

test('row 0 is correctly handled (not confused with undefined)', () => {
  const manifests = [{
    groups: [
      { name: 'g0', label: 'G0', style: 'default', order: 0, row: 0, col: 0, nodes: ['a'] },
      { name: 'g1', label: 'G1', style: 'default', order: 1, row: 1, col: 0, nodes: ['b'] },
    ],
    edges: [],
  }]
  const result = computeManifestLayout(nodes, manifests)
  assert.ok(result)
  // row 0 should be above row 1
  assert.ok(result.positions.a.y < result.positions.b.y, 'row 0 should be above row 1')
})

test('legacy fallback: vertical stacking when no row/col', () => {
  const manifests = [{
    groups: [
      { name: 'g1', label: 'G1', style: 'default', order: 0, nodes: ['a', 'b'] },
      { name: 'g2', label: 'G2', style: 'default', order: 1, nodes: ['c'] },
    ],
    edges: [],
  }]
  const result = computeManifestLayout(nodes, manifests)
  assert.ok(result, 'should return a result')
  // g2 should be below g1 in vertical stacking
  assert.ok(result.positions.c.y > result.positions.a.y, 'group 2 below group 1')
})

test('encrypted style populates encryptedIds', () => {
  const manifests = [{
    groups: [
      { name: 'enc', label: 'Enc', style: 'encrypted', order: 0, row: 0, col: 0, nodes: ['a', 'b'] },
      { name: 'plain', label: 'Plain', style: 'default', order: 1, row: 0, col: 1, nodes: ['c'] },
    ],
    edges: [],
  }]
  const result = computeManifestLayout(nodes, manifests)
  assert.ok(result.encryptedIds.includes('a'), 'a should be encrypted')
  assert.ok(result.encryptedIds.includes('b'), 'b should be encrypted')
  assert.ok(!result.encryptedIds.includes('c'), 'c should not be encrypted')
})

test('manifest edges collected from all manifests', () => {
  const manifests = [
    {
      order: 0,
      groups: [{ name: 'g1', style: 'default', order: 0, row: 0, col: 0, nodes: ['a'] }],
      edges: [{ source: 'a', target: 'b', label: 'e1' }],
    },
    {
      order: 1,
      groups: [{ name: 'g2', style: 'default', order: 0, row: 0, col: 0, nodes: ['d'] }],
      edges: [{ source: 'd', target: 'e', label: 'e2' }],
    },
  ]
  const result = computeManifestLayout(nodes, manifests)
  assert.ok(result)
  assert.equal(result.manifestEdges.length, 2)
  assert.equal(result.manifestEdges[0].source, 'a')
  assert.equal(result.manifestEdges[1].source, 'd')
})

test('all groups rendered including those without topology match', () => {
  const manifests = [{
    groups: [
      { name: 'manifest-only', label: 'Manifest', style: 'default', order: 0, row: 0, col: 0, nodes: ['x', 'y'] },
      { name: 'both', label: 'Both', style: 'default', order: 1, row: 0, col: 1, nodes: ['a'] },
    ],
    edges: [],
  }]
  const result = computeManifestLayout(nodes, manifests)
  assert.ok(result)
  assert.equal(result.groups.length, 2, 'both groups rendered — manifest is source of truth')
  assert.equal(result.groups[0].label, 'Manifest')
  assert.equal(result.groups[1].label, 'Both')
})

test('planned style sets planned flag on group', () => {
  const manifests = [{
    groups: [
      { name: 'p', label: 'Planned', style: 'planned', order: 0, row: 0, col: 0, nodes: ['a'] },
    ],
    edges: [],
  }]
  const result = computeManifestLayout(nodes, manifests)
  assert.ok(result.groups[0].planned, 'group should be planned')
  assert.ok(!result.groups[0].encrypted, 'group should not be encrypted')
})

test('multi-column groups spread nodes across columns', () => {
  const manifests = [{
    groups: [
      { name: 'wide', label: 'Wide', style: 'default', order: 0, row: 0, col: 0, columns: 3, nodes: ['a', 'b', 'c', 'd', 'e'] },
    ],
    edges: [],
  }]
  const result = computeManifestLayout(nodes, manifests)
  assert.ok(result)
  // Nodes a, b, c should be in the same row (row 0), d, e in row 1
  assert.equal(result.positions.a.y, result.positions.b.y, 'a and b same row')
  assert.equal(result.positions.a.y, result.positions.c.y, 'a and c same row')
  assert.ok(result.positions.d.y > result.positions.a.y, 'd in next row')
  assert.equal(result.positions.d.y, result.positions.e.y, 'd and e same row')
  // a, b, c should have different x positions
  assert.ok(result.positions.b.x > result.positions.a.x, 'b right of a')
  assert.ok(result.positions.c.x > result.positions.b.x, 'c right of b')
})

test('edge status defaults to healthy', () => {
  const manifests = [{
    groups: [{ name: 'g', style: 'default', order: 0, row: 0, col: 0, nodes: ['a'] }],
    edges: [
      { source: 'a', target: 'b', label: 'normal' },
      { source: 'a', target: 'c', label: 'down', status: 'planned' },
    ],
  }]
  const result = computeManifestLayout(nodes, manifests)
  assert.equal(result.manifestEdges[0].status, 'healthy')
  assert.equal(result.manifestEdges[1].status, 'planned')
})

test('REQ-213: manifestNodesById includes nodes not placed in any group', () => {
  // pl-mig is the parent of a dynamic group but not listed in any group.nodes,
  // so it is not in manifestNodes. manifestNodesById must still contain it
  // for the click handler to resolve.
  const manifests = [{
    groups: [
      { name: 'lb', style: 'default', order: 0, row: 0, col: 0, label: 'LB', nodes: ['pl-lb'] },
      { name: 'mig', style: 'encrypted', order: 1, row: 0, col: 1, label: 'MIG',
        dynamic: true, parent: 'pl-mig', nodes: [] },
    ],
    nodes: [
      { id: 'pl-lb', label: 'Load Balancer', type: 'load_balancer' },
      { id: 'pl-mig', label: 'Confidential VM (MIG)', type: 'mig',
        monitoring: { logs: [{ project: 'p', filter: 'resource.type="gce_instance"' }] } },
    ],
    edges: [],
  }]
  const result = computeManifestLayout([], manifests)
  assert.ok(result.manifestNodesById, 'manifestNodesById should exist')
  assert.ok(result.manifestNodesById['pl-mig'], 'pl-mig present even though not in any group.nodes')
  assert.equal(result.manifestNodesById['pl-mig'].type, 'mig')
  assert.ok(result.manifestNodesById['pl-mig'].monitoring?.logs?.[0]?.filter,
    'monitoring.logs survives so click handler can surface it')
})

test('REQ-213: dynamic group exposes parent on the rendered group object', () => {
  const manifests = [{
    groups: [
      { name: 'mig', style: 'encrypted', order: 0, row: 0, col: 0,
        dynamic: true, parent: 'pl-mig', nodes: [], label: 'Confidential VM (MIG)' },
    ],
    nodes: [
      { id: 'pl-mig', label: 'MIG', type: 'mig', monitoring: { probe: { type: 'gcp_vm_status' } } },
    ],
    edges: [],
  }]
  const topo = [{ id: 'vm-example-mig-abc', label: 'VM: abc', type: 'vm',
    metrics: { _parent: 'pl-mig' } }]
  const result = computeManifestLayout(topo, manifests)
  assert.ok(result, 'layout should compute')
  const migGroup = result.groups.find(g => g._name === 'mig')
  assert.ok(migGroup, 'mig group rendered')
  assert.equal(migGroup.parent, 'pl-mig',
    'group.parent passes through so TopologyMap click handler can resolve it')
})

test('REQ-213: static (non-dynamic) groups expose parent=null', () => {
  const manifests = [{
    groups: [
      { name: 'providers', style: 'partner', order: 0, row: 0, col: 0,
        nodes: ['p1'], label: 'Providers' },
    ],
    nodes: [{ id: 'p1', label: 'Provider', type: 'provider' }],
    edges: [],
  }]
  const result = computeManifestLayout([], manifests)
  const g = result.groups.find(gg => gg._name === 'providers')
  assert.equal(g.parent, null, 'static group has parent=null (no dynamic anchor)')
})

test('REQ-213: buildParentNodeRecord merges manifest authority with live topology', () => {
  const mNode = {
    id: 'pl-mig', label: 'Confidential VM (MIG)', type: 'mig',
    project_id: 'nr-prod',
    cost_yearly_usd: 2400,
    monitoring: {
      probe: { type: 'gcp_vm_status', resource_name: 'example-mig' },
      logs: [{ project: 'nr-prod', filter: 'resource.type="gce_instance"' }],
    },
  }
  const topoNode = {
    id: 'pl-mig', label: 'pl-mig', type: 'infra',
    status: 'healthy', metrics: { cpu_percent: 23 },
    last_checked: '2026-04-27T10:00:00Z',
    project: 'platform', env: 'prod', project_id: 'nr-prod',
  }
  const rec = buildParentNodeRecord('pl-mig', mNode, topoNode)
  assert.equal(rec.id, 'pl-mig')
  assert.equal(rec.label, 'Confidential VM (MIG)', 'manifest label wins over topology label')
  assert.equal(rec.type, 'mig', 'manifest type wins over topology generic')
  assert.equal(rec.status, 'healthy', 'topology status pulled in')
  assert.deepEqual(rec.metrics, { cpu_percent: 23 }, 'topology metrics pulled in')
  assert.equal(rec.cost_yearly_usd, 2400)
  assert.ok(rec.monitoring?.probe, 'full monitoring (probe) preserved for live monitoring panel')
  assert.equal(rec.monitoring_logs?.[0]?.filter, 'resource.type="gce_instance"',
    'monitoring_logs surfaced for log modal')
  assert.equal(rec.last_checked, '2026-04-27T10:00:00Z')
  assert.equal(rec.source, 'manifest')
})

test('REQ-213: buildParentNodeRecord preserves zero cost (no || coercion)', () => {
  const mNode = { id: 'free-node', type: 'storage', cost_yearly_usd: 0 }
  const rec = buildParentNodeRecord('free-node', mNode, null)
  assert.equal(rec.cost_yearly_usd, 0,
    'zero is a legitimate cost value, must not be coerced to null by ||')
})

test('REQ-213: buildParentNodeRecord works when one of mNode/topoNode is missing', () => {
  // Only manifest entry (e.g. node not yet in topology API response)
  const onlyManifest = buildParentNodeRecord('pl-mig',
    { id: 'pl-mig', label: 'MIG', type: 'mig' }, null)
  assert.equal(onlyManifest.label, 'MIG')
  assert.equal(onlyManifest.status, 'unknown')

  // Only topology entry (e.g. discovered node without manifest declaration)
  const onlyTopo = buildParentNodeRecord('discovered',
    null, { id: 'discovered', label: 'Discovered', type: 'vm', status: 'healthy' })
  assert.equal(onlyTopo.label, 'Discovered')
  assert.equal(onlyTopo.status, 'healthy')
  assert.equal(onlyTopo.cost_yearly_usd, null,
    'manifest absent → cost_yearly_usd defaults to null cleanly')
})

test('REQ-213: layout shell still emitted when manifest has nodes but no positions', () => {
  // Manifest with only a parent node and an empty dynamic group — nothing to render
  // but click handler must still resolve manifestNodesById.
  const manifests = [{
    groups: [
      { name: 'mig', style: 'encrypted', order: 0, row: 0, col: 0,
        dynamic: true, parent: 'pl-mig', nodes: [] },
    ],
    nodes: [{ id: 'pl-mig', type: 'mig', monitoring: { probe: { type: 'gcp_vm_status' } } }],
    edges: [],
  }]
  const result = computeManifestLayout([], manifests)
  assert.ok(result, 'should not be null when manifestNodesById has entries')
  assert.ok(result.manifestNodesById['pl-mig'], 'parent node accessible')
  assert.equal(Object.keys(result.positions).length, 0, 'no positions because nothing to place')
})

console.log('\nDone.')
