// File: frontend/src/utils/coldvaultMetrics.test.js
// Purpose: REQ-GHA-025 — metrics that were not read say why and when
// Run: node frontend/src/utils/coldvaultMetrics.test.js

import assert from 'node:assert/strict'
import { metricsNotRead } from './coldvaultMetrics.js'

let failed = 0
function test(name, fn) {
  try { fn(); console.log(`  ✅ ${name}`) } catch (e) { failed++; console.error(`  ❌ ${name}\n     ${e.message}`) }
}

test('gives the reason and the UTC time', () => {
  const at = Date.UTC(2026, 10, 6, 11, 5) / 1000
  assert.equal(metricsNotRead({ read: false, reason: 'ColdVault refused the request (HTTP 403)', checked_at: at }),
    'ColdVault metrics not read: ColdVault refused the request (HTTP 403) · 11:05 UTC')
})

test('works before the first attempt', () => {
  assert.equal(metricsNotRead({ read: false, reason: 'not read yet', checked_at: null }),
    'ColdVault metrics not read: not read yet')
})

if (failed) { console.error(`${failed} failed`); process.exit(1) }
