// REQ-GHA-050
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { evaluatedWhen, outOfDate, nextState } from './evaluationAge.js'

const tz = { timeZone: 'Europe/Zurich' }
const now = Date.parse('2026-11-10T16:00:00Z')

test('clause 1: time alone today, yesterday, then a date', () => {
  assert.equal(evaluatedWhen(Date.parse('2026-11-10T14:35:00Z'), now, tz), '15:35 CET')
  assert.equal(evaluatedWhen(Date.parse('2026-11-09T14:35:00Z'), now, tz), 'yesterday 15:35 CET')
  assert.equal(evaluatedWhen(Date.parse('2026-11-03T14:35:00Z'), now, tz), '3 Nov, 15:35 CET')
  assert.equal(evaluatedWhen(Date.parse('2025-11-03T14:35:00Z'), now, tz), '3 Nov 2025, 15:35 CET')
  // the day after the spring change, 30 Mar 00:30 CEST: 29 Mar is yesterday, 28 Mar is not
  assert.equal(evaluatedWhen(Date.parse('2026-03-29T08:00:00Z'), Date.parse('2026-03-29T22:30:00Z'), tz), 'yesterday 10:00 CEST')
  assert.equal(evaluatedWhen(Date.parse('2026-03-28T22:00:00Z'), Date.parse('2026-03-29T22:30:00Z'), tz), '28 Mar, 23:00 CET')
})

test('clause 2: current up to 4 hours, out of date after', () => {
  assert.equal(outOfDate(now - 3.5 * 3600e3, now, 'waiting'), null)
  assert.equal(outOfDate(now - 4 * 3600e3, now, 'waiting'), null)
  assert.equal(outOfDate(now - 5 * 3600e3, now, 'waiting').mark, 'Out of date · 5 hours old')
  assert.equal(outOfDate(now - 2 * 86400e3, now, 'waiting').mark, 'Out of date · 2 days old')
})

test('clause 4: only the true line', () => {
  const old = now - 86400e3
  assert.equal(outOfDate(old, now, 'running').next, 'A new evaluation is running.')
  assert.equal(outOfDate(old, now, 'failed').next, 'The new evaluation failed; it will be tried again.')
  assert.equal(outOfDate(old, now, 'waiting').next, 'Waiting for a new evaluation.')
  assert.equal(nextState({ job: { status: 'running' } }), 'running')
  assert.equal(nextState({ job: { status: 'retrying' } }), 'failed')
  assert.equal(nextState({ error: 'x' }), 'failed')
  assert.equal(nextState({}, true), 'running')
  assert.equal(nextState({}), 'waiting')
})
