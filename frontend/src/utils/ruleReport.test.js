// File: frontend/src/utils/ruleReport.test.js
// Purpose: REQ-GHA-031 — a rule alarm's report follows what the check observed
// Run: node frontend/src/utils/ruleReport.test.js

import assert from 'node:assert/strict'
import { ruleReport } from './ruleReport.js'

const alarm = (probe_type, status, result) => ({ title: 'x: service check failed', part_label: 'x', metric_name: 'status',
  first_seen: '2026-11-08T10:00:00Z', check: { probe_type, status, result } })

const endpoint = ruleReport(alarm('http', 'error', 'HTTP 503 from https://app.example/health'))
assert.equal(endpoint.signal, 'HTTP 503 from https://app.example/health')
assert.match(endpoint.action, /open this address/)

const targets = ruleReport(alarm('aws_target_group', 'error', '0 of 1 application targets pass'))
assert.equal(targets.signal, '0 of 1 application targets pass')
assert.match(targets.action, /unhealthy target/)
assert.doesNotMatch(targets.action, /open this address/)

const unread = ruleReport(alarm('aws_log_group', 'not checked', 'GlassHood could not read this AWS resource (ClientError)'))
assert.match(unread.impact, /state is unknown/)
assert.match(unread.action, /read access/)
assert.notEqual(unread.action, ruleReport(alarm('aws_log_group', 'error', 'y')).action)

const service = ruleReport(alarm('aws_ecs_service', 'error', 'Service unavailable: 0 of 1 tasks running'))
assert.ok(service.causes.every(c => /may/.test(c)))
assert.match(service.action, /ECS service events/)

const numeric = ruleReport({ part_label: 'x', severity: 'critical', metric_name: 'cpu', metric_value: 95, threshold: 90, message: 'cpu high' })
assert.doesNotMatch(numeric.impact, /cannot confirm|unavailable\.$/)
assert.match(numeric.impact, /does not show that the service is unavailable/)
assert.equal(numeric.signal, 'cpu: 95 (threshold 90).')

assert.deepEqual(ruleReport({ part_label: 'x', metric_name: 'status' }).causes, [])
console.log('ruleReport tests passed')
