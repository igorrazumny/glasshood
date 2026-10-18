// File: frontend/src/utils/activity.test.js
// Purpose: REQ-GHA-018 — use reporting throttle, use-token storage, waking-page URL,
// the wake client (renewal, retry, timeouts) and passive background failures
// Run: node frontend/src/utils/activity.test.js

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createThrottle, createWakeClient, readUseToken, storeUseToken, USE_THROTTLE_MS } from './activity.js'
import { wakeConfig, wakingPageUrl } from '../config/wake.js'

const _tests = []
function test(name, fn) { _tests.push([name, fn]) }
async function run() {
  for (const [name, fn] of _tests) {
    try {
      await fn()
      console.log(`  ✅ ${name}`)
    } catch (e) {
      console.error(`  ❌ ${name}`)
      console.error(`     ${e.message}`)
      process.exitCode = 1
    }
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

// A scripted controller: each path answers from its own list, in order.
// An answer is {status, body}, 'hang' (headers never come) or 'hang-body'.
function fakeController(script) {
  const calls = []
  const fetchFn = (url, init) => {
    const path = url.replace('https://c.example', '')
    calls.push({ path, body: init.body ? JSON.parse(init.body) : null })
    const a = (script[path] || []).shift() || { status: 500, body: {} }
    if (a === 'hang') return new Promise(() => {})
    if (a === 'hang-body') return Promise.resolve({ status: 200, json: () => new Promise(() => {}) })
    return Promise.resolve({ status: a.status, json: async () => a.body })
  }
  return { calls, fetchFn }
}

function manualTimers() {
  const timers = new Map(); let id = 0
  return {
    setTimer: (fn) => { timers.set(++id, fn); return id },
    clearTimer: (i) => timers.delete(i),
    fireAll: () => { for (const [i, fn] of [...timers]) { timers.delete(i); fn() } },
  }
}

function client(script, { token, hidden = false, timers } = {}) {
  const ctl = fakeController(script)
  const storage = memoryStorage()
  if (token) storeUseToken(token, storage)
  const loc = { pathname: '/', search: '', hash: '', replaced: [], replace(u) { this.replaced.push(u) } }
  let captchas = 0
  const c = createWakeClient({
    controller: 'https://c.example', fetchFn: ctl.fetchFn, storage, loc,
    recaptchaToken: async () => { captchas++; return 'rc' },
    isHidden: () => hidden, now: () => Date.parse('2026-10-18T10:00:00Z'),
    ...(timers ? { setTimer: timers.setTimer, clearTimer: timers.clearTimer } : {}),
  })
  return { c, ctl, storage, loc, captchas: () => captchas }
}

const OLD = { use_token: 'old', use_token_expires: '2026-10-18T09:00:00Z' }
const NEW = { use_token: 'new', use_token_expires: '2026-10-18T13:00:00Z' }
const flush = () => new Promise((r) => setTimeout(r, 0))

test('stale token while awake: fresh reCAPTCHA, new token, the same use sent again', async () => {
  const k = client({
    '/use': [{ status: 403, body: { error: 'token' } }, { status: 204 }],
    '/status': [{ status: 200, body: { state: 'awake' } }],
    '/wake': [{ status: 202, body: NEW }],
  }, { token: OLD })
  await k.c.sendUse()
  assert.deepEqual(k.ctl.calls.map((x) => x.path), ['/use', '/status', '/wake', '/use'])
  assert.equal(k.ctl.calls[2].body.recaptcha_token, 'rc')
  assert.equal(k.ctl.calls[3].body.use_token, 'new')
  assert.equal(readUseToken(k.storage).use_token, 'new')
  assert.equal(k.captchas(), 1)
  assert.deepEqual(k.loc.replaced, [])
})

test('the next use after a renewal goes straight through with the new token', async () => {
  const k = client({
    '/use': [{ status: 403 }, { status: 204 }, { status: 204 }],
    '/status': [{ status: 200, body: { state: 'awake' } }],
    '/wake': [{ status: 202, body: NEW }],
  }, { token: OLD })
  await k.c.sendUse(); await k.c.sendUse()
  assert.deepEqual(k.ctl.calls.map((x) => x.path), ['/use', '/status', '/wake', '/use', '/use'])
  assert.equal(k.captchas(), 1)
})

test('stale token while asleep: to the waking page, no renewal', async () => {
  const k = client({ '/use': [{ status: 403 }], '/status': [{ status: 200, body: { state: 'asleep' } }] }, { token: OLD })
  await k.c.sendUse()
  assert.deepEqual(k.ctl.calls.map((x) => x.path), ['/use', '/status'])
  assert.equal(k.loc.replaced.length, 1)
  assert.equal(k.captchas(), 0)
})

test('a renewed token refused again is not retried in a loop', async () => {
  const k = client({
    '/use': [{ status: 403 }, { status: 403 }],
    '/status': [{ status: 200, body: { state: 'awake' } }],
    '/wake': [{ status: 202, body: NEW }],
  }, { token: OLD })
  await k.c.sendUse()
  assert.deepEqual(k.ctl.calls.map((x) => x.path), ['/use', '/status', '/wake', '/use'])
})

test('no token while awake: reCAPTCHA first, then the use', async () => {
  const k = client({
    '/status': [{ status: 200, body: { state: 'awake' } }],
    '/wake': [{ status: 202, body: NEW }],
    '/use': [{ status: 204 }],
  })
  await k.c.sendUse()
  assert.deepEqual(k.ctl.calls.map((x) => x.path), ['/status', '/wake', '/use'])
})

test('a hidden tab reports nothing and goes nowhere', async () => {
  const k = client({}, { token: OLD, hidden: true })
  await k.c.sendUse()
  assert.equal(k.ctl.calls.length, 0)
  assert.deepEqual(k.loc.replaced, [])
})

for (const hang of ['hang', 'hang-body']) {
  test(`status check that stalls (${hang}) ends at the waking page`, async () => {
    const timers = manualTimers()
    const k = client({ '/status': [hang] }, { timers })
    let result = 'pending'
    k.c.checkAwake().then((r) => { result = r })
    await flush()
    assert.equal(result, 'pending')
    timers.fireAll()
    await flush()
    assert.equal(result, false)
    assert.equal(k.loc.replaced.length, 1)
  })
}

test('a use report that stalls settles and goes nowhere', async () => {
  const timers = manualTimers()
  const k = client({ '/use': ['hang'] }, { token: NEW, timers })
  let done = false
  k.c.sendUse().then(() => { done = true })
  await flush(); timers.fireAll(); await flush()
  assert.equal(done, true)
  assert.deepEqual(k.loc.replaced, [])
})

test('failed API requests stay passive: api.js never enters the wake flow', () => {
  const src = readFileSync(new URL('./api.js', import.meta.url), 'utf8')
  assert.doesNotMatch(src, /from '\.\/activity|ensureAwake|checkAwake|location\.replace/)
})

run()
