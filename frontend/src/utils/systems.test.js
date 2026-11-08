// File: frontend/src/utils/systems.test.js
// Purpose: REQ-GHA-035 — system cards for the home view
// Run: node frontend/src/utils/systems.test.js

import assert from 'node:assert/strict'
import { systemCards, systemOfNodes, portfolioLine, systemId, groupedCards, cardsInGroup } from './systems.js'

let failed = 0
function test(name, fn) {
  try { fn(); console.log(`  ✅ ${name}`) } catch (e) { failed++; console.error(`  ❌ ${name}\n     ${e.message}`) }
}

const manifests = [
  { product: 'coldvault', environment: 'prod', solution: 'ColdVault', display_name: 'coldvault.ai' },
  { product: 'cloudflare', environment: 'public', solution: 'Cloudflare', kind: 'outside_view' },
]
const nodes = [
  { id: 'cv-a', project: 'coldvault', env: 'prod', status: 'healthy', metrics: { _last_poll: 100 } },
  { id: 'cv-b', project: 'coldvault', env: 'prod', status: 'degraded', metrics: { _last_poll: 200 } },
  { id: 'cv-c', project: 'coldvault', env: 'prod', status: 'not checked' },
  { id: 'cf-ams', project: 'cloudflare', env: 'public', status: 'healthy' },
  { id: 'cf-fra', project: 'cloudflare', env: 'public', status: 'error' },
  { id: 'loose', project: '', env: '', status: 'error' },
]
const alerts = [
  { node_id: 'cv-b', severity: 'critical' }, { node_id: 'cf-fra', severity: 'warning' },
  { node_id: 'loose', severity: 'critical' },
]

test('each box belongs to the system its landscape names', () => {
  const m = systemOfNodes(nodes, manifests)
  assert.equal(m.get('cv-a'), systemId(manifests[0]))
  assert.equal(m.get('cf-fra'), 'manifest-cloudflare-public')
  assert.equal(m.has('loose'), false)
})

test('a card says the state in one plain line and counts its own alarms', () => {
  const [cv, cf] = systemCards(manifests, nodes, alerts)
  assert.equal(cv.label, 'ColdVault')
  assert.equal(cv.state, 'degraded')
  assert.equal(cv.line, 'Running, with problems in 1 part')
  assert.deepEqual([cv.critical, cv.warning, cv.parts, cv.checkedAt], [1, 0, 3, 200])
  assert.equal(cf.outside, true)
  assert.equal(cf.line, 'The provider reports outages in 1 part')
  assert.deepEqual([cf.critical, cf.warning], [0, 1])
})

test('a system nobody could read is never shown as working', () => {
  const [c] = systemCards([manifests[0]], [{ id: 'x', project: 'coldvault', env: 'prod', status: 'not checked' }], [])
  assert.equal(c.state, 'not checked')
  assert.equal(c.line, 'Not checked yet')
})

test('idle parts are not counted as unread', () => {
  const [c] = systemCards([manifests[0]], [
    { id: 'a', project: 'coldvault', env: 'prod', status: 'healthy' },
    { id: 'b', project: 'coldvault', env: 'prod', status: 'idle' }], [])
  assert.equal(c.line, 'Running normally')
})

test('an alarm on a box inside a server counts for its system', () => {
  // shadow C2: vm-a is tagged ColdVault; its app child is failing and has a critical alarm
  const nested = [{ id: 'vm-a', project: 'coldvault', env: 'prod', status: 'healthy',
    children: [{ id: 'vm-a-api', status: 'error', children: [{ id: 'vm-a-api-x', status: 'healthy' }] }] }]
  const owner = systemOfNodes(nested, manifests)
  assert.equal(owner.get('vm-a-api'), 'manifest-coldvault-prod')
  assert.equal(owner.get('vm-a-api-x'), 'manifest-coldvault-prod')
  const [c] = systemCards([manifests[0]], nested, [{ node_id: 'vm-a-api', severity: 'critical' }])
  assert.equal(c.critical, 1)
  assert.equal(c.state, 'error')
  assert.equal(c.parts, 3)
})

test('the portfolio line counts systems that need attention', () => {
  const cards = systemCards(manifests, nodes, alerts)
  assert.equal(portfolioLine(cards), '2 systems · 2 need attention')
  assert.equal(portfolioLine([{ state: 'healthy', critical: 0 }]), '1 system · none needs attention')
})

test('systems are grouped as 9Robots systems and external systems', () => {
  const cards = systemCards(manifests, nodes, alerts)
  const groups = groupedCards(cards)
  assert.deepEqual(groups.map(g => [g.group.label, g.cards.map(c => c.label)]),
    [['9Robots systems', ['ColdVault']], ['External systems', ['Cloudflare']]])
  assert.deepEqual(cardsInGroup(cards, 'group-external').map(c => c.label), ['Cloudflare'])
  assert.equal(cardsInGroup(cards, null).length, 2)
})

test('a group with no systems is not shown', () => {
  const groups = groupedCards(systemCards([manifests[0]], nodes, alerts))
  assert.deepEqual(groups.map(g => g.group.label), ['9Robots systems'])
})

if (failed) { console.error(`${failed} failed`); process.exit(1) }
