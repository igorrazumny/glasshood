// File: frontend/src/utils/alarms.test.js
// Purpose: REQ-GHA-027 — alarm lines are plain, current and listed once
// Run: node frontend/src/utils/alarms.test.js

import assert from 'node:assert/strict'
import { alarmLevel, alarmsByLevel, defaultOpen, alarmWhen, resolvedWhen, alarmTitle, notCheckedNames, alarmKindLabel, sortAlarms,
  alarmTag, alarmRef, patternLabel, errorText } from './alarms.js'
import { zoneName } from './time.js'

let failed = 0
function test(name, fn) {
  try { fn(); console.log(`  ✅ ${name}`) } catch (e) { failed++; console.error(`  ❌ ${name}\n     ${e.message}`) }
}

const t = (h, m) => new Date(2026, 10, 6, h, m).toISOString()
const Z = zoneName(t(10, 46))  // REQ-GHA-030: the reader's zone is named

test('says since when and when last seen', () => {
  assert.equal(alarmWhen({ first_seen: t(10, 46), last_seen: t(11, 2) }), `since 10:46 ${Z} · last seen 11:02 ${Z}`)
  assert.equal(alarmWhen({ first_seen: t(10, 46), last_seen: t(10, 46) }), `since 10:46 ${Z}`)
})

test('gives start and end of a resolved alarm', () => {
  assert.equal(resolvedWhen({ first_seen: t(9, 5), ended_at: t(9, 40) }), `09:05–09:40 ${Z}`)
})

test('shows the plain title, the technical message only when there is no title', () => {
  assert.equal(alarmTitle({ title: 'Backend service: responses are slow (1200 ms on average)',
    message: 'High load balancer latency: lb_latency_ms=1200' }), 'Backend service: responses are slow (1200 ms on average)')
  assert.equal(alarmTitle({ message: 'x' }), 'x')
})

test('lists each unchecked rule name once, and not when a sibling rule was checked', () => {
  const rules = [
    { id: 'ram_high', name: 'Memory use', checked: false },
    { id: 'ram_critical', name: 'Memory use', checked: false },
    { id: 'lb_latency_high', name: 'Response time', checked: true },
    { id: 'lb_latency_critical', name: 'Response time', checked: false },
    { id: 'disk_full', name: 'Disk space', checked: false },
  ]
  assert.deepEqual(notCheckedNames(rules), ['Memory use', 'Disk space'])
  assert.deepEqual(notCheckedNames(undefined), [])
})

test('REQ-GHA-028: examples and observations are marked; real alarms are not', () => {
  assert.equal(alarmKindLabel({ kind: 'example' }), 'example')
  assert.equal(alarmKindLabel({ kind: 'observation' }), 'observation')
  assert.equal(alarmKindLabel({ kind: 'alarm' }), '')
  assert.equal(alarmKindLabel({}), '')
})

test('REQ-GHA-028: critical first, then real alarms before examples', () => {
  const list = [
    { id: 'ex', severity: 'warning', kind: 'example' },
    { id: 'real', severity: 'warning', kind: 'alarm' },
    { id: 'crit', severity: 'critical', kind: 'alarm' },
    { id: 'obs', severity: 'warning', kind: 'observation' },
  ]
  assert.deepEqual(sortAlarms(list).map(a => a.id), ['crit', 'real', 'ex', 'obs'])
  assert.deepEqual(sortAlarms(undefined), [])
})

test('an alarm the AI review found is tagged and sorts with the real alarms (REQ-GHA-029)', () => {
  const ai = { kind: 'ai', severity: 'critical' }
  assert.equal(alarmTag(ai), 'AI review')
  assert.equal(alarmTag({ kind: 'example' }), 'example')
  assert.equal(alarmTag({ kind: 'alarm' }), '')
  const ex = { kind: 'example', severity: 'critical' }
  assert.deepEqual(sortAlarms([ex, ai]), [ai, ex])
})

test('finds an alarm by its group and part, the rule id for older ones', () => {
  assert.deepEqual(alarmRef({ group: 'ai:ab12', rule_id: 'ai_review', node_id: 'cv-mig' }), { group: 'ai:ab12', node_id: 'cv-mig' })
  assert.deepEqual(alarmRef({ rule_id: 'cpu_high' }), { group: 'cpu_high', node_id: null })
})

test('says in plain words whether it is ongoing or happened once', () => {
  assert.equal(patternLabel('once'), 'Happened once')
  assert.equal(patternLabel('ongoing'), 'Still going on')
  assert.equal(patternLabel('whatever'), 'Not clear yet')
})

test('shows the server reason of a refused request', () => {
  assert.equal(errorText(new Error('409: {"detail":"daily cap of 30 investigations reached"}')), 'daily cap of 30 investigations reached')
  assert.equal(errorText(new Error('Unauthorized')), 'Unauthorized')
})

test('the newest alarm comes first within the same severity and kind', () => {
  const list = [
    { id: 'old', severity: 'warning', first_seen: '2026-11-07T10:00:00+00:00' },
    { id: 'new', severity: 'warning', first_seen: '2026-11-08T00:30:00+00:00' },
    { id: 'crit-old', severity: 'critical', first_seen: '2026-11-06T10:00:00+00:00' },
  ]
  assert.deepEqual(sortAlarms(list).map(a => a.id), ['crit-old', 'new', 'old'])
})

test('alarms map onto the five severity levels', () => {
  assert.equal(alarmLevel({ severity: 'critical', kind: 'ai' }), 'critical')
  assert.equal(alarmLevel({ severity: 'warning', kind: 'alarm' }), 'medium')
  assert.equal(alarmLevel({ severity: 'warning', kind: 'observation' }), 'info')
  assert.equal(alarmLevel({ severity: 'critical', kind: 'example' }), 'example')
  assert.equal(alarmLevel({ severity: 'info', group: 'provider:Cloudflare:m1', title: 'MSP (maintenance, reported by Cloudflare)' }), 'info')
  // shadow P1 on #123: a disruptive maintenance keeps its level; the title alone decides nothing
  assert.equal(alarmLevel({ severity: 'warning', group: 'provider:Cloudflare:m2', title: 'Network (maintenance, reported by Cloudflare)' }), 'medium')
  assert.equal(alarmLevel({ severity: 'warning', group: 'provider:Cloudflare:i1', title: 'Spectrum (incident, reported by Cloudflare)' }), 'medium')
})

test('critical and high open first; medium only when nothing is more urgent', () => {
  const by = alarmsByLevel([{ severity: 'critical' }, { severity: 'warning' }, { severity: 'warning', kind: 'observation' }])
  assert.deepEqual(Object.keys(by).sort(), ['critical', 'info', 'medium'])
  assert.deepEqual(defaultOpen(by), { critical: true, high: true, medium: false, low: false, info: false, example: false })
  assert.equal(defaultOpen(alarmsByLevel([{ severity: 'warning' }])).medium, true)
})

test('each severity list is newest first, whatever an alarm\'s original severity or kind', () => {
  // shadow P2 on #123: an old observation must not sit above a new information alarm
  const by = alarmsByLevel([
    { severity: 'warning', kind: 'observation', first_seen: '2026-11-01T10:00:00Z', title: 'old note' },
    { severity: 'info', kind: 'alarm', first_seen: '2026-11-08T10:00:00Z', title: 'new info' },
  ])
  assert.deepEqual(by.info.map(a => a.title), ['new info', 'old note'])
})

if (failed) { console.error(`${failed} failed`); process.exit(1) }
