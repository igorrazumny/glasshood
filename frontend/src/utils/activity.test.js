// File: frontend/src/utils/activity.test.js
// Purpose: REQ-GHA-018 — use reporting throttle, use-token storage, waking-page URL
// Run: node frontend/src/utils/activity.test.js

import assert from 'node:assert/strict'
import { createThrottle, readUseToken, storeUseToken, USE_THROTTLE_MS } from './activity.js'
import { wakeConfig, wakingPageUrl } from '../config/wake.js'

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

function fakeClock() {
  let t = 0
  const timers = []
  return {
    now: () => t,
    setTimer: (fn, ms) => timers.push({ at: t + ms, fn }),
    advance(ms) {
      t += ms
      for (const x of timers.splice(0)) {
        if (x.at <= t) x.fn(); else timers.push(x)
      }
    },
  }
}

function memoryStorage() {
  const m = new Map()
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)) }
}

console.log('activity')

test('first use is sent at once', () => {
  const c = fakeClock(); let sent = 0
  const trigger = createThrottle(() => sent++, USE_THROTTLE_MS, c.now, c.setTimer)
  trigger()
  assert.equal(sent, 1)
})

test('uses inside the window are sent once when the window ends, not dropped', () => {
  const c = fakeClock(); let sent = 0
  const trigger = createThrottle(() => sent++, 60_000, c.now, c.setTimer)
  trigger(); c.advance(10_000); trigger(); trigger(); c.advance(20_000); trigger()
  assert.equal(sent, 1)
  c.advance(30_000)
  assert.equal(sent, 2)
})

test('a use after a quiet window is sent at once again', () => {
  const c = fakeClock(); let sent = 0
  const trigger = createThrottle(() => sent++, 60_000, c.now, c.setTimer)
  trigger(); c.advance(61_000); trigger()
  assert.equal(sent, 2)
})

test('no use, no send: an untouched tab reports nothing', () => {
  const c = fakeClock(); let sent = 0
  createThrottle(() => sent++, 60_000, c.now, c.setTimer)
  c.advance(10 * 60_000)
  assert.equal(sent, 0)
})

test('use token round-trips and bad storage reads as none', () => {
  const s = memoryStorage()
  assert.equal(readUseToken(s), null)
  storeUseToken({ use_token: 'abc', use_token_expires: '2026-10-18T12:00:00Z' }, s)
  assert.equal(readUseToken(s).use_token, 'abc')
  s.setItem('glasshood_use_token', '{not json')
  assert.equal(readUseToken(s), null)
})

test('waking page keeps path, query and hash', () => {
  const url = wakingPageUrl({ pathname: '/demo', search: '?x=1', hash: '#n' }, '/waking/')
  assert.equal(url, '/waking/?next=%2Fdemo%3Fx%3D1%23n')
})

test('config: unset means same origin and no controller; trailing slashes dropped', () => {
  assert.deepEqual(wakeConfig({}), { apiBase: '', controller: '', recaptchaSiteKey: '', wakingPage: '/waking/' })
  const c = wakeConfig({ VITE_API_BASE: 'https://a.example/', VITE_CONTROLLER: 'https://c.example//' })
  assert.equal(c.apiBase, 'https://a.example')
  assert.equal(c.controller, 'https://c.example')
})
