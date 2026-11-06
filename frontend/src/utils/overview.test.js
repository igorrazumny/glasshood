// File: frontend/src/utils/overview.test.js
// Purpose: REQ-GHA-024 — the overview says when it was written (not by which model), and the spend
// Run: node frontend/src/utils/overview.test.js

import assert from 'node:assert/strict'
import { ago, overviewStamp, spendLine, isStale } from './overview.js'

let failed = 0
function test(name, fn) {
  try { fn(); console.log(`  ✅ ${name}`) } catch (e) { failed++; console.error(`  ❌ ${name}\n     ${e.message}`) }
}

const now = Date.UTC(2026, 10, 6, 12, 0, 0)

test('age reads in plain words', () => {
  assert.equal(ago(now / 1000 - 30, now), 'just now')
  assert.equal(ago(now / 1000 - 600, now), '10 min ago')
  assert.equal(ago(now / 1000 - 3 * 3600, now), '3 h ago')
  assert.equal(ago(now / 1000 - 2 * 86400, now), '2 d ago')
})

test('stamp names the time and the age, never the model', () => {
  const s = overviewStamp({ analyzed_at: now / 1000 - 3600, model: 'gemini-3.1-flash-lite' }, now)
  assert.match(s, /^Updated \S+.*, 1 h ago$/)
  assert.doesNotMatch(s, /gemini/)
})

test('no overview yet says so', () => {
  assert.equal(overviewStamp({ analyzed_at: null, model: 'm' }, now), 'Not written yet')
  assert.equal(overviewStamp(undefined, now), 'Not written yet')
})

test('spend line shows calls, cost and cap; says when the cap stopped it', () => {
  assert.equal(spendLine({ calls: 39, cost_usd: 0.0081, daily_call_cap: 1200, capped: false }),
    'Today: 39 model calls, about $0.01 (cap 1200 calls)')
  assert.match(spendLine({ calls: 1200, cost_usd: 1.9, daily_call_cap: 1200, capped: true }), /daily cap reached/)
})

test('stale by age while a modal stays open, even if fetched fresh', () => {
  const o = { analyzed_at: now / 1000 - 2 * 3600, interval_s: 10800, stale: false }
  assert.equal(isStale(o, now), false)
  assert.equal(isStale(o, now + 2 * 3600 * 1000), true)
  assert.equal(isStale({ analyzed_at: null }, now), false)
})

test('spend line says when today\'s usage could not be read', () => {
  assert.match(spendLine({ calls: 0, cost_usd: 0, daily_call_cap: 1200, usage_read: false,
    read_error: "today's model usage could not be read (RuntimeError)" }), /no new overviews until it can be read/)
})

if (failed) { console.error(`${failed} failed`); process.exit(1) }
