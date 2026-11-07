// File: frontend/src/utils/time.test.js
// Purpose: REQ-GHA-030 — times are in the reader's zone and always name it
// Run: node frontend/src/utils/time.test.js

import assert from 'node:assert/strict'
import { clock, dateTime, clockRange, zoneName } from './time.js'

let failed = 0
function test(name, fn) {
  try { fn(); console.log(`  ✅ ${name}`) } catch (e) { failed++; console.error(`  ❌ ${name}\n     ${e.message}`) }
}

const at = Date.UTC(2026, 10, 7, 11, 53, 7)

test('a Zurich reader sees CET', () => {
  assert.equal(clock(at, { timeZone: 'Europe/Zurich' }), '12:53 CET')
})

test('a summer time is named as such', () => {
  assert.equal(clock(Date.UTC(2026, 6, 1, 10, 0), { timeZone: 'Europe/Zurich' }), '12:00 CEST')
})

test('a UTC reader sees UTC', () => {
  assert.equal(clock(new Date(at).toISOString(), { timeZone: 'UTC' }), '11:53 UTC')
})

test('another zone shifts the clock and names its zone', () => {
  const s = clock(at, { timeZone: 'America/New_York' })
  assert.ok(s.startsWith('06:53 '), s)
  assert.ok(zoneName(at, 'America/New_York').length > 0)
})

test('seconds when asked', () => {
  assert.equal(clock(at, { timeZone: 'UTC', seconds: true }), '11:53:07 UTC')
})

test('date and time carry the zone', () => {
  assert.equal(dateTime(at, { timeZone: 'Europe/Zurich' }), '7 Nov 2026, 12:53 CET')
})

test('a range names the shared zone once', () => {
  assert.equal(clockRange(Date.UTC(2026, 10, 7, 8, 5), Date.UTC(2026, 10, 7, 8, 40), { timeZone: 'Europe/Zurich' }),
    '09:05–09:40 CET')
})

test('nothing for a missing or broken time', () => {
  assert.equal(clock(null), '')
  assert.equal(clock('not a time'), '')
  assert.equal(dateTime(''), '')
})

if (failed) { console.error(`${failed} failed`); process.exit(1) }
