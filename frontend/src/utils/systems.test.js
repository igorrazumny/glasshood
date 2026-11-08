// File: frontend/src/utils/systems.test.js
// Purpose: REQ-GHA-035 — system cards for the home view
// Run: node frontend/src/utils/systems.test.js

import assert from 'node:assert/strict'
import { headerLine, systemCards, systemOfNodes, portfolioLine, systemId, groupedCards, cardsInGroup, assessmentLine, listAssessments } from './systems.js'

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

test('an old assessment and a failed refresh are both said, the old text kept', () => {
  const now = Date.UTC(2026, 10, 8, 1, 37)
  const a = assessmentLine({ summary: 'ColdVault is running normally.', analyzed_at: (now - 24 * 3600e3) / 1000,
    stale: true, error: 'daily cap reached' }, now)
  assert.equal(a.text, 'ColdVault is running normally.')
  assert.match(a.when, /^written 7 Nov/)
  assert.match(a.old, /24 h old/)
  assert.equal(a.problem, 'Latest update failed: daily cap reached')
  const fresh = assessmentLine({ summary: 'ok', analyzed_at: (now - 600e3) / 1000, stale: false }, now)
  assert.equal(fresh.old, null); assert.equal(fresh.problem, null); assert.match(fresh.when, /^written \d\d:\d\d \S+$/)
  assert.equal(assessmentLine(null, now).text, 'Being written; it appears within a few minutes.')
})

test('the header says what it covers', () => {
  const cards = systemCards(manifests, nodes, alerts)
  assert.equal(headerLine(cards, null).text, 'Our systems: 1 needs attention · External services: 1 needs attention')
  assert.equal(headerLine(cards, 'manifest-coldvault-prod').text, 'ColdVault: needs attention')
  assert.equal(headerLine(cards, 'group-external').text, 'External services: 1 needs attention')
  assert.equal(headerLine([], null).text, 'Loading your systems…')
})

test('configuration notes are counted apart from alerts to review', () => {
  const [c] = systemCards([manifests[0]], nodes, [{ node_id: 'cv-a', severity: 'warning', kind: 'observation' },
    { node_id: 'cv-a', severity: 'warning', kind: 'alarm' }, { node_id: 'cv-a', severity: 'warning', kind: 'example' }])
  assert.deepEqual([c.warning, c.notes], [1, 1])
})

test('external trouble alone makes the header amber, not red', () => {
  const cards = systemCards(manifests, nodes.filter(n => n.id !== 'cv-b'), [])
  assert.equal(headerLine(cards, null).state, 'degraded')
})

test('the home list says each assessment\'s age and a failed update, as the card does', () => {
  // shadow C1 on #123: a day-old summary with a failed refresh must not read as current
  const now = Date.parse('2026-11-08T12:00:00Z')
  const cards = [{ id: 'a', label: 'One', product: 'one' }, { id: 'b', label: 'Two', product: 'two' }, { id: 'c', label: 'Three', product: 'three' }]
  const [one, two, three] = listAssessments(cards, {
    one: { summary: 'Old healthy assessment', analyzed_at: (now - 24 * 3600e3) / 1000, stale: true, error: 'daily cap reached' },
    two: { summary: 'Fine', analyzed_at: (now - 600e3) / 1000 },
  }, now)
  assert.equal(one.text, 'Old healthy assessment')
  assert.match(one.when, /^written /); assert.match(one.old, /24 h old/)
  assert.equal(one.problem, 'Latest update failed: daily cap reached')
  assert.equal(two.old, null); assert.equal(two.problem, null); assert.equal(two.waiting, false)
  assert.equal(three.waiting, true); assert.equal(three.when, null)
})

test('a group with an unassessed system never claims it operates normally', () => {
  // shadow P1 on #123
  const cards = [{ id: 'x', label: 'A', state: 'healthy' }, { id: 'y', label: 'B', state: 'not checked' }]
  const line = headerLine(cards.map(c => ({ ...c, outside: false, critical: 0 })), null).text
  assert.equal(line, 'Our systems: 1 operating normally, 1 status unavailable')
})

if (failed) { console.error(`${failed} failed`); process.exit(1) }
