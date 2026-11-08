// File: frontend/src/utils/authSignal.test.js
// Purpose: shadow P1 on #131 — a final refusal of the current session's credentials still logs
// out (the app is told), while a late refusal from an earlier session changes nothing

import assert from 'node:assert/strict'

const store = new Map()
globalThis.sessionStorage = { getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, String(v)), removeItem: k => store.delete(k) }
globalThis.window = new EventTarget()
let pending = []
globalThis.fetch = () => new Promise(resolve => pending.push(resolve))
const refuse = () => ({ status: 401, ok: false, clone() { return this }, json: async () => ({ detail: 'invalid token' }), text: async () => '' })

const { apiFetch, setToken, clearToken, getToken, AUTH_FAILED_EVENT } = await import('./api.js')

let failed = 0
async function test(name, fn) {
  try { await fn(); console.log(`  ✅ ${name}`) } catch (e) { failed++; console.error(`  ❌ ${name}\n     ${e.message}`) }
}
let signals = 0
window.addEventListener(AUTH_FAILED_EVENT, () => signals++)

await test('a refused current session is ended and the app is told', async () => {
  signals = 0; pending = []
  setToken('current')
  const read = apiFetch('/api/topology')
  await new Promise(r => setTimeout(r, 0))
  pending.shift()(refuse())
  await assert.rejects(read, /Unauthorized/)
  assert.equal(signals, 1)
  assert.equal(getToken(), null)
})

await test('a late refusal from an earlier session logs nobody out', async () => {
  signals = 0; pending = []
  setToken('operator')
  const old = apiFetch('/api/topology')
  await new Promise(r => setTimeout(r, 0))
  clearToken(); setToken('viewer')          // logout, next person logs in
  pending.shift()(refuse())
  await assert.rejects(old, /Unauthorized/)
  assert.equal(signals, 0)
  assert.equal(getToken(), 'viewer')
})

if (failed) { console.error(`${failed} failed`); process.exit(1) }
