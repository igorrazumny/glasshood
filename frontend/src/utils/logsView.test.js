// File: frontend/src/utils/logsView.test.js
// Purpose: REQ-GHA-032 (amended 2026-11-09) — View Logs only where logs can be opened; the window keeps
// what it loaded. Run: node frontend/src/utils/logsView.test.js

import assert from 'node:assert/strict'
import { noLogsReason, mergeEntries, earlierLines, earlierRequest, EARLIER_LIMIT, PAGE, EARLIER_EMPTY } from './logsView.js'

let failed = 0
function test(name, fn) {
  try { fn(); console.log(`  ✅ ${name}`) } catch (e) { failed++; console.error(`  ❌ ${name}\n     ${e.message}`) }
}

test('a box whose landscape file says it has no log source gets the reason, every other box null', () => {
  assert.equal(noLogsReason({ monitoring_logs: [{ source: 'none', reason: 'Access logging is disabled.' }] }), 'Access logging is disabled.')
  assert.equal(noLogsReason({ monitoring_logs: [{ source: 'none' }] }), 'This part writes no logs GlassHood can read.')
  assert.equal(noLogsReason({ monitoring: { logs: [{ source: 'none', reason: 'Static site.' }] } }), 'Static site.')
  assert.equal(noLogsReason({ monitoring_logs: [{ project: 'p', filter: 'f' }] }), null)
  assert.equal(noLogsReason({ monitoring_logs: null }), null)      // no logs block: the project default applies
  assert.equal(noLogsReason({}), null)
  assert.equal(noLogsReason(null), null)
})

test('loaded lines are kept oldest first, nothing is removed, duplicates join once', () => {
  const a = { timestamp: '2026-11-09T10:00:00Z', severity: 'INFO', message: 'a' }
  const b = { timestamp: '2026-11-09T10:00:01Z', severity: 'INFO', message: 'b' }
  const c = { timestamp: '2026-11-09T10:00:02Z', severity: 'ERROR', message: 'c' }
  const first = mergeEntries([], [c, b])                 // the API answers newest first
  assert.deepEqual(first.map(e => e.message), ['b', 'c'])
  const refreshed = mergeEntries(first, [c, b])           // the 30-second refresh repeats what is shown
  assert.equal(refreshed, first)
  const newer = mergeEntries(first, [{ timestamp: '2026-11-09T10:00:03Z', severity: 'INFO', message: 'd' }, c])
  assert.deepEqual(newer.map(e => e.message), ['b', 'c', 'd'])
  const earlier = mergeEntries(newer, [a])
  assert.deepEqual(earlier.map(e => e.message), ['a', 'b', 'c', 'd'])
  assert.equal(mergeEntries(earlier, []).length, 4)
  assert.equal(mergeEntries(null, null).length, 0)
})

test('lines sharing a timestamp are separate occurrences and can all be reached across a page boundary', () => {
  const t = '2026-11-09T10:00:00Z'
  const line = { timestamp: t, severity: 'INFO', message: 'same' }
  assert.equal(mergeEntries([line], [{ ...line }, { ...line }]).length, 2)
  assert.equal(mergeEntries([line, { ...line }], [{ ...line }]).length, 2)
  const page = Array.from({ length: 300 }, () => ({ ...line }))
  assert.equal(earlierLines(page), 600)
  assert.equal(mergeEntries(page, Array.from({ length: 301 }, () => ({ ...line }))).length, 301)
})

test('a moment with more lines than a request carries never blocks older history', () => {
  const t = '2026-11-09T10:00:00.000Z'
  const line = { timestamp: t, severity: 'INFO', message: 'same' }
  assert.deepEqual(earlierRequest([line]), { lines: PAGE + 1, before: t, skipped: false })
  const full = Array.from({ length: EARLIER_LIMIT }, () => ({ ...line }))
  assert.deepEqual(earlierRequest(full), { lines: PAGE, before: '2026-11-09T09:59:59.999Z', skipped: true })
})

test('the page is several screens and the empty-earlier note is fixed', () => {
  assert.ok(PAGE >= 300)
  assert.equal(EARLIER_EMPTY, 'No earlier lines in the last 7 days.')
})

if (failed) { console.error(`${failed} failed`); process.exit(1) }
