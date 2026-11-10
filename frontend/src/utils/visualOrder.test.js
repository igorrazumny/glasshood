// File: frontend/src/utils/visualOrder.test.js
// Purpose: REQ-GHA-045 clauses 4, 5 and 8. Run: node frontend/src/utils/visualOrder.test.js
import assert from 'node:assert/strict'
import { statusWord, statusReason, headerLine } from './systems.js'
import { alarmAgo } from './alarms.js'

assert.deepEqual(['healthy', 'degraded', 'error', 'not checked'].map(statusWord), ['Healthy', 'Needs attention', 'Degraded', 'Unknown'])
assert.equal(statusReason({ notes: 8 }), '8 configuration notes')
assert.equal(statusReason({ critical: 1, warning: 1, notes: 3 }), '2 alerts (1 critical)')
const cards = [{ id: 'a', label: 'A', product: 'a', state: 'healthy' }, { id: 'b', label: 'B', product: 'b', state: 'degraded', notes: 1 }]
assert.match(headerLine(cards, 'b').text, /B: Needs attention$/)
assert.equal(alarmAgo({ first_seen: new Date(900000).toISOString() }, 1800000), '15 min ago')

import { changeLines } from './systems.js'
assert.equal(changeLines({ first_run: true }).none, 'Nothing to compare yet')
assert.equal(changeLines({ added: [], removed: [], changed: [] }).none, 'No changes')
assert.deepEqual(changeLines({ added: ['b'], removed: [], changed: [{ id: 'a', before: { label: 'A', status: 'healthy' }, after: { label: 'A', status: 'error' } }] }).lines, ['A: healthy to error', 'b: new'])
assert.equal(changeLines({ added: ['a', 'b', 'c'], removed: [], changed: [] }, 2).more, 1)

import { scopeDiff } from './systems.js'
const owners = new Map([['own', 'c1'], ['cf', 'c2']])
const d = { added: [], removed: ['gone'], changed: [{ id: 'cf', before: { status: 'healthy' }, after: { status: 'error' } }, { id: 'own', before: { status: 'healthy' }, after: { status: 'error' } }] }
const s = scopeDiff(d, owners, new Set(['c1']))
assert.deepEqual(s.changed.map(c => c.id), ['own'])
assert.deepEqual(s.removed, [])
assert.equal(s.unassigned, 1)
assert.equal(changeLines(s).unassigned, 1)

import { clampSplit } from './panelSplit.js'
assert.equal(clampSplit(0.01), 0.15)
assert.equal(clampSplit(0.99), 0.85)
assert.equal(clampSplit('x'), 0.5)

import { loadSplit } from './panelSplit.js'
import { selectionNotice } from './systems.js'
assert.equal(await loadSplit(async () => ({ split: 0.3 })), 0.3)
assert.equal(await loadSplit(async () => ({ split: null })), null)
assert.equal(selectionNotice({ summary: 'x', current: true }), null)
assert.equal(selectionNotice({ summary: 'x', current: false }), null)
assert.equal(selectionNotice({ summary: 'x', current: false, update_failed: true }), 'The latest update of this review could not be written.')

assert.equal(changeLines({ added: ['a'], removed: [], changed: [], previous_at: 123 }).previousAt, 123)
assert.equal(changeLines({ added: [], removed: [], changed: [] }).none, 'No changes')
