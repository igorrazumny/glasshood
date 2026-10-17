// File: frontend/src/config/auth0Flag.test.js
// Purpose: REQ-GHA-017 — Auth0 stays off unless the build explicitly turns it on
// Run: node frontend/src/config/auth0Flag.test.js

import assert from 'node:assert/strict'
import { isAuth0Enabled } from './auth0Flag.js'

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

test('off when the variable is absent', () => assert.equal(isAuth0Enabled({}), false))
test('off when env itself is missing', () => assert.equal(isAuth0Enabled(undefined), false))
test('off for anything but the exact string true', () => {
  for (const v of ['false', '1', 'TRUE', 'yes', '', ' true']) {
    assert.equal(isAuth0Enabled({ VITE_AUTH0_ENABLED: v }), false, v)
  }
})
test('on only for true', () => assert.equal(isAuth0Enabled({ VITE_AUTH0_ENABLED: 'true' }), true))
