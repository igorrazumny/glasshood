// File: frontend/src/utils/systems.test.js
// Purpose: REQ-GHA-035 — system cards for the home view
// Run: node frontend/src/utils/systems.test.js

import assert from 'node:assert/strict'
import { systemCards, systemOfNodes, portfolioLine, systemId } from './systems.js'

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
  assert.equal(cv.line, '1 part with problems, checked · 1 not checked')
  assert.deepEqual([cv.critical, cv.warning, cv.parts, cv.checkedAt], [1, 0, 3, 200])
  assert.equal(cf.outside, true)
  assert.equal(cf.line, '1 part failing, reported by the provider')
  assert.deepEqual([cf.critical, cf.warning], [0, 1])
})

test('a system nobody could read is never shown as working', () => {
  const [c] = systemCards([manifests[0]], [{ id: 'x', project: 'coldvault', env: 'prod', status: 'not checked' }], [])
  assert.equal(c.state, 'not checked')
  assert.match(c.line, /^Not checked yet/)
})

test('idle parts are not counted as unread', () => {
  const [c] = systemCards([manifests[0]], [
    { id: 'a', project: 'coldvault', env: 'prod', status: 'healthy' },
    { id: 'b', project: 'coldvault', env: 'prod', status: 'idle' }], [])
  assert.equal(c.line, 'All 1 checked parts working')
})

test('the portfolio line counts systems that need attention', () => {
  const cards = systemCards(manifests, nodes, alerts)
  assert.equal(portfolioLine(cards), '2 systems · 2 need attention')
  assert.equal(portfolioLine([{ state: 'healthy', critical: 0 }]), '1 system · none needs attention')
})

if (failed) { console.error(`${failed} failed`); process.exit(1) }
