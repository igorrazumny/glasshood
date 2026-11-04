// File: frontend/src/utils/mcpRecheck.test.js
// Purpose: REQ-GHA-020 — Recheck via MCP: who sees it and how results read
// Run: node frontend/src/utils/mcpRecheck.test.js

import assert from 'node:assert/strict'
import { canRecheck, describeRecheck, recheckError } from './mcpRecheck.js'

let failed = 0
function test(name, fn) {
  try { fn(); console.log(`  ✅ ${name}`) } catch (e) { failed++; console.error(`  ❌ ${name}\n     ${e.message}`) }
}

const node = { source: 'manifest', mcp_recheck: true }

test('offered on a manifest node with an MCP recheck', () => assert.equal(canRecheck(node, false), true))
test('never in Live demo', () => assert.equal(canRecheck(node, true), false))
test('offered on a template child with an MCP recheck', () => {
  const child = { source: 'manifest', monitoring: { recheck: { type: 'mcp_ask', url: 'u' } } }
  assert.equal(canRecheck(child, false), true)
  assert.equal(canRecheck(child, true), false)
  assert.equal(canRecheck({ source: 'manifest', monitoring: { recheck: { type: 'other' } } }, false), false)
})
test('not on nodes without an MCP recheck', () => {
  assert.equal(canRecheck({ source: 'manifest' }, false), false)
  assert.equal(canRecheck({ ...node, source: 'gcp' }, false), false)
  assert.equal(canRecheck(null, false), false)
})
test('an answer names the model, time and mode, never the text', () => {
  const s = describeRecheck({ ok: true, model: 'gemma-3', elapsed_s: 4.2, mode: 'vault', answer: 'secret' })
  assert.equal(s, 'Answered by gemma-3 in 4.2s (Vault Mode).')
  assert.ok(!s.includes('secret'))
})
test('a failure gives the reason', () => {
  assert.equal(describeRecheck({ ok: false, reason: 'All models failed to respond.', mode: 'vault' }),
    'No answer (Vault Mode): All models failed to respond.')
  assert.match(describeRecheck({ ok: false, mode: 'partner' }), /Partner Mode.*unknown reason/)
})
test('server detail is shown for refusals', () => {
  assert.equal(recheckError(new Error('429: {"detail":"Next recheck possible in 42s"}')), 'Next recheck possible in 42s')
  assert.equal(recheckError(new Error('502: <html>')), 'Recheck failed (HTTP 502)')
  assert.equal(recheckError(new Error('Failed to fetch')), 'Failed to fetch')
})

if (failed) { console.error(`${failed} failed`); process.exit(1) }
