// File: frontend/src/utils/pollCache.test.js
// Purpose: shadow C1 on #130 — one session's answers never reach the next session

import assert from 'node:assert/strict'
import { sessionEpoch, newSession, stored, store } from './pollCache.js'

let failed = 0
function test(name, fn) {
  try { fn(); console.log(`  ✅ ${name}`) } catch (e) { failed++; console.error(`  ❌ ${name}\n     ${e.message}`) }
}

test('a stored answer is shown again in the same session', () => {
  newSession()
  const ep = sessionEpoch()
  assert.equal(store('/api/analysis', { summary: 'A' }, 1, ep), true)
  assert.deepEqual(stored('/api/analysis').data, { summary: 'A' })
})

test('logout empties the store', () => {
  newSession()
  store('/api/analysis', { summary: 'operator' }, 1, sessionEpoch())
  newSession()
  assert.equal(stored('/api/analysis'), null)
})

test('an answer from before a logout is refused, before and after the next login', () => {
  newSession()
  const operator = sessionEpoch()            // request started in the operator's session
  newSession()                               // logout
  assert.equal(store('/api/analysis', { spend: 1 }, 1, operator), false)
  assert.equal(stored('/api/analysis'), null)
  newSession()                               // viewer logs in
  assert.equal(store('/api/analysis', { spend: 1 }, 2, operator), false)
  assert.equal(stored('/api/analysis'), null)
  assert.equal(store('/api/analysis', { summary: 'viewer' }, 3, sessionEpoch()), true)
  assert.deepEqual(stored('/api/analysis').data, { summary: 'viewer' })
})

if (failed) { console.error(`${failed} failed`); process.exit(1) }
