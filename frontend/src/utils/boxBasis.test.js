// File: frontend/src/utils/boxBasis.test.js
// Purpose: REQ-GHA-044 clauses 3, 4 and 8. Run: node frontend/src/utils/boxBasis.test.js
import assert from 'node:assert/strict'
import { boxBasis } from './boxBasis.js'

assert.equal(boxBasis({ status: 'healthy', metrics: { _probe_type: 'http' } }), 'Answers at its address')
assert.equal(boxBasis({ status: 'healthy', metrics: { _probe_type: 'aws_ecs_service' } }), 'Provider reports its state')
assert.equal(boxBasis({ status: 'error', metrics: { _probe_type: 'http', _check_description: 'HTTP probe FAILED' } }), 'Check result: HTTP probe FAILED')
assert.equal(boxBasis({ status: 'healthy', metrics: { cpu: 3 } }), 'Measurements read')
assert.equal(boxBasis({ status: 'not checked', metrics: { _check_description: 'No access' } }), 'Not checked: No access')
assert.equal(boxBasis({ status: 'not monitored', metrics: {} }), 'Not checked: no check result is available')
assert.equal(boxBasis({ status: 'planned', metrics: {} }), 'Set up but not in use')
