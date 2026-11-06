// File: frontend/src/utils/alarms.test.js
// Purpose: REQ-GHA-027 — alarm lines are plain, current and listed once
// Run: node frontend/src/utils/alarms.test.js

import assert from 'node:assert/strict'
import { alarmWhen, resolvedWhen, alarmTitle, notCheckedNames } from './alarms.js'

let failed = 0
function test(name, fn) {
  try { fn(); console.log(`  ✅ ${name}`) } catch (e) { failed++; console.error(`  ❌ ${name}\n     ${e.message}`) }
}

const t = (h, m) => new Date(2026, 10, 6, h, m).toISOString()

test('says since when and when last seen', () => {
  assert.equal(alarmWhen({ first_seen: t(10, 46), last_seen: t(11, 2) }), 'since 10:46 · last seen 11:02')
  assert.equal(alarmWhen({ first_seen: t(10, 46), last_seen: t(10, 46) }), 'since 10:46')
})

test('gives start and end of a resolved alarm', () => {
  assert.equal(resolvedWhen({ first_seen: t(9, 5), ended_at: t(9, 40) }), '09:05–09:40')
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

if (failed) { console.error(`${failed} failed`); process.exit(1) }
