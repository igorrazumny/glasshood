// File: frontend/src/utils/systems.test.js
// Purpose: REQ-GHA-035 — system cards for the home view
// Run: node frontend/src/utils/systems.test.js

import assert from 'node:assert/strict'
import { TREE_LEFT, headerLine, withRecords, offlineLine, systemCards, systemOfNodes, portfolioLine, systemId, groupedCards, cardsInGroup, assessmentLine, listAssessments, loadFailed, staleDataLine } from './systems.js'

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
  assert.deepEqual([cv.critical, cv.warning, cv.parts], [1, 0, 3])
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

test('systems are grouped as Proprietary systems and External systems', () => {
  const cards = systemCards(manifests, nodes, alerts)
  const groups = groupedCards(cards)
  assert.deepEqual(groups.map(g => [g.group.label, g.cards.map(c => c.label)]),
    [['Proprietary systems', ['ColdVault']], ['External systems', ['Cloudflare']]])
  assert.deepEqual(cardsInGroup(cards, 'group-external').map(c => c.label), ['Cloudflare'])
  assert.equal(cardsInGroup(cards, null).length, 2)
})

test('a group with no systems is not shown', () => {
  const groups = groupedCards(systemCards([manifests[0]], nodes, alerts))
  assert.deepEqual(groups.map(g => g.group.label), ['Proprietary systems'])
})

test('an old assessment keeps its text without an age warning; a failed refresh is said', () => {
  const now = Date.UTC(2026, 10, 8, 1, 37)
  const a = assessmentLine({ summary: 'ColdVault is running normally.', analyzed_at: (now - 24 * 3600e3) / 1000,
    stale: true, error: 'daily cap reached' }, now)
  assert.equal(a.text, 'ColdVault is running normally.')
  assert.match(a.when, /^evaluated 7 Nov/)
  assert.equal(a.old, undefined)
  assert.equal(a.problem, 'Latest update failed: daily cap reached')
  const fresh = assessmentLine({ summary: 'ok', analyzed_at: (now - 600e3) / 1000, stale: false }, now)
  assert.equal(fresh.problem, null); assert.match(fresh.when, /^evaluated \d\d:\d\d \S+$/)
  assert.equal(assessmentLine(null, now).text, 'AI evaluation has not started yet.')
  assert.equal(assessmentLine(null, now).busy, false)
  assert.equal(assessmentLine({ job: { status: 'running' } }, now).text, 'AI evaluation in progress.')
  assert.equal(assessmentLine({ job: { status: 'retrying' } }, now).busy, true)
  assert.equal(assessmentLine({ job: { status: 'failed', attempts: 1 }, error: 'x' }, now).text, 'The AI evaluation failed.')
  assert.equal(assessmentLine({ job: { status: 'failed', attempts: 3 }, error: 'x' }, now).text, 'The AI evaluation failed after 3 attempts.')
  const kept = s => assessmentLine({ summary: 'Fine', job: { status: s } }, now)
  assert.equal(kept('running').text, 'Fine')
  assert.notEqual(kept('running').job, kept('retrying').job)
  assert.match(kept('failed').job, /next scheduled round/)
  assert.equal(kept('complete').job, null)
})

test('the header says what it covers', () => {
  const cards = systemCards(manifests, nodes, alerts)
  assert.equal(headerLine(cards, null).text, 'Our systems: 1 needs attention · External services: 1 needs attention')
  assert.equal(headerLine(cards, 'manifest-coldvault-prod').text, 'ColdVault: Needs attention')
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
  assert.match(one.when, /^evaluated /); assert.equal(one.old, undefined)
  assert.equal(one.problem, 'Latest update failed: daily cap reached')
  assert.equal(two.problem, null); assert.equal(two.waiting, false)
  assert.equal(three.waiting, false); assert.equal(three.when, null); assert.equal(three.text, 'AI evaluation has not started yet.')
})

test('a group with an unassessed system never claims it operates normally', () => {
  // shadow P1 on #123
  const cards = [{ id: 'x', label: 'A', state: 'healthy' }, { id: 'y', label: 'B', state: 'not checked' }]
  const line = headerLine(cards.map(c => ({ ...c, outside: false, critical: 0 })), null).text
  assert.equal(line, 'Our systems: 1 operating normally, 1 status unavailable')
})

test('a failed read is said in plain words, never shown as still loading', () => {
  // REQ-GHA-037 clause 6; shadow's pre-existing gap on #123
  assert.equal(loadFailed('The AI overview', '503: {"detail":"x"}'), 'The AI overview could not be loaded ({"detail":"x"}); trying again.')
  const [row] = listAssessments([{ id: 'a', label: 'One', product: 'one' }], {}, Date.now(), 'Failed to fetch')
  assert.equal(row.waiting, false)
  assert.equal(row.text, 'The assessment could not be loaded (Failed to fetch); trying again.')
})

test('a failed refresh is said beside an assessment that is kept', () => {
  // shadow P1 on #129: a cached summary must not hide that the newer read failed
  const now = Date.now()
  const [row] = listAssessments([{ id: 'a', label: 'One', product: 'one' }],
    { one: { summary: 'Fine', analyzed_at: (now - 600e3) / 1000 } }, now, 'Failed to fetch')
  assert.equal(row.text, 'Fine')
  assert.equal(row.problem, 'A newer assessment could not be loaded (Failed to fetch); trying again.')
})

test('a failed refresh with older data says so and when that data is from', () => {
  // shadow on #130: a failed topology refresh must not look current
  const line = staleDataLine('Failed to fetch', Date.parse('2026-11-08T01:00:00Z'))
  assert.match(line, /^Could not refresh \(Failed to fetch\); showing the data from \d\d:\d\d \S+\. Trying again\.$/)
  assert.equal(staleDataLine(null, Date.now()), null)
})

test('each step down the projects tree is the same distance', () => {
  // the dot's position: chevron left + width + right, then the row's own padding
  const all = 8 + 14 + 4 + 12
  const group = TREE_LEFT.groupChevron + 13 + 2 + 12
  assert.equal(group - all, TREE_LEFT.system - group)
  assert.equal(TREE_LEFT.system - group, 11)
})

test('only our own systems carry a logo', () => {
  const [cv, cf] = systemCards(manifests, nodes, alerts)
  assert.equal(cv.logo, '/logos/coldvault.png')
  assert.equal(cf.logo, null)
  assert.equal(systemCards([{ product: 'other', environment: 'x' }], [], [])[0].logo, null)
})

test('a card says only what its saved record says', () => {
  const base = [{ id: 'a', product: 'a', outside: false, state: 'healthy', line: 'live', critical: 9, warning: 9, notes: 9 }]
  const [c] = withRecords(base, { a: { condition: 'attention', summary: 'One part needs attention', alerts: [{ severity: 'warning', kind: 'alarm' }] } })
  assert.deepEqual([c.state, c.line, c.critical, c.warning], ['degraded', 'Running, with something that needs attention', 0, 1])
})

test('a system with no record is never shown as working', () => {
  const base = [{ id: 'a', product: 'a', state: 'healthy', line: 'Running normally', critical: 1 }]
  assert.equal(withRecords(base, {})[0].state, 'not checked')
  assert.equal(withRecords(base, {})[0].line, 'Not assessed yet')
  assert.equal(withRecords(base, { a: { error: 'x' } })[0].state, 'not checked')
  assert.equal(withRecords(base, null)[0].line, 'Status not available yet')
})

test('one system with no record does not read as operational', () => {
  const [c] = withRecords([{ id: 'a', product: 'a', label: 'A', outside: false, state: 'healthy' }], {})
  assert.equal(headerLine([c], null).text, 'Our systems: status not available')
  assert.notEqual(headerLine([c], null).state, 'healthy')
})

test('a blocked AI provider is on the card even with no record', () => {
  const [c] = withRecords([{ id: 'g', product: 'g' }], { g: { critical_notice: 'OpenAI is blocked' } })
  assert.equal(c.notice, 'OpenAI is blocked')
  assert.equal(c.state, 'not checked')
})

test('AI offline: grey, one line, the number, and never a colour from the old record', () => {
  const ai_offline = { since: '2026-11-08T16:10:00Z', alert: 48213 }
  const [c] = withRecords([{ id: 'a', product: 'a', label: 'A', outside: false, state: 'healthy' }],
    { a: { ai_offline, condition: 'failing', summary: 'old', alerts: [{ severity: 'critical' }] } })
  assert.equal(c.state, 'not checked'); assert.equal(c.critical, 0)
  assert.match(c.line, /^AI evaluation offline since .*\. See alert 48213 for details\.$/)
  assert.doesNotMatch(c.line, /system/i)
  assert.equal(headerLine([c], null).text, c.line)
  assert.equal(headerLine([c], null).state, 'unknown')
  assert.equal(headerLine([c], null).offline, ai_offline)
  const [row] = listAssessments([{ id: 'a', label: 'A', product: 'a' }], { a: { ai_offline, summary: 'old', analyzed_at: 1 } }, Date.now())
  assert.equal(row.offline, ai_offline); assert.equal(row.last.text, 'old')
})

if (failed) { console.error(`${failed} failed`); process.exit(1) }
