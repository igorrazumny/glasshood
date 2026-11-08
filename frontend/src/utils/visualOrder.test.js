// File: frontend/src/utils/visualOrder.test.js
// Purpose: REQ-GHA-045 clauses 4, 5 and 8. Run: node frontend/src/utils/visualOrder.test.js
import assert from 'node:assert/strict'
import { statusWord, statusReason, attentionItems, headerLine } from './systems.js'
import { alarmAgo } from './alarms.js'

assert.deepEqual(['healthy', 'degraded', 'error', 'not checked'].map(statusWord), ['Healthy', 'Needs attention', 'Degraded', 'Unknown'])
assert.equal(statusReason({ notes: 8 }), '8 configuration notes')
assert.equal(statusReason({ critical: 1, warning: 1, notes: 3 }), '2 alerts (1 critical)')
const cards = [{ id: 'a', label: 'A', product: 'a', state: 'healthy' }, { id: 'b', label: 'B', product: 'b', state: 'degraded', notes: 1 }]
assert.deepEqual(attentionItems(cards, { b: { summary: 'same text as the card', issues: ['x'] } }),
  [{ id: 'b', label: 'B', word: 'Needs attention', reason: '1 configuration note', issues: ['x'] }])
assert.equal(headerLine(cards, 'b').text, 'B: Needs attention')
assert.equal(alarmAgo({ first_seen: new Date(900000).toISOString() }, 1800000), '15 min ago')

import { changeLines } from './systems.js'
assert.equal(changeLines({ first_run: true }).none, 'Nothing to compare yet')
assert.equal(changeLines({ added: [], removed: [], changed: [] }).none, 'No changes')
assert.deepEqual(changeLines({ added: ['b'], removed: [], changed: [{ id: 'a', before: { label: 'A', status: 'healthy' }, after: { label: 'A', status: 'error' } }] }).lines, ['A: healthy to error', 'b: new'])
assert.equal(changeLines({ added: ['a', 'b', 'c'], removed: [], changed: [] }, 2).more, 1)
