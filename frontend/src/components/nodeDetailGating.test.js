// File: frontend/src/components/nodeDetailGating.test.js
// Purpose: Test manifest node gating logic from NodeDetailModal (R30 fix + monitoring)
// Verifies: banner, live metrics, AI analysis, and logs button visibility rules
// Run: node frontend/src/components/nodeDetailGating.test.js

import assert from 'node:assert/strict'

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

// Extract the gating logic from NodeDetailModal.jsx as pure functions
// These mirror the exact conditionals in the component

function _hasLiveMetrics(node) {
  if (!node.metrics) return false
  const metricKeys = Object.keys(node.metrics).filter(k => !k.startsWith('_') && k !== 'note')
  return metricKeys.length > 0 && metricKeys.some(k => node.metrics[k] !== null)
}

function showNotMonitoredBanner(node) {
  return node.source === 'manifest' && !_hasLiveMetrics(node)
}

function showLiveMetrics(node) {
  return node.source === 'manifest' && _hasLiveMetrics(node)
}

function showAIAnalysis(node, isDemo) {
  return !isDemo && node.source !== 'manifest'
}

function showLogsDisabled(node) {
  return node.source === 'manifest'
}

console.log('NodeDetailModal gating tests (R30 fix + monitoring):')

// --- Banner tests (shows when NO live metrics) ---

test('manifest node with status "not monitored" shows banner', () => {
  assert.equal(showNotMonitoredBanner({ source: 'manifest', status: 'not monitored' }), true)
})

test('manifest node with status "dynamic" shows banner', () => {
  assert.equal(showNotMonitoredBanner({ source: 'manifest', status: 'dynamic' }), true)
})

test('manifest node with null status shows banner (R30 regression case)', () => {
  assert.equal(showNotMonitoredBanner({ source: 'manifest', status: null }), true)
})

test('manifest node with undefined status shows banner (R30 regression case)', () => {
  assert.equal(showNotMonitoredBanner({ source: 'manifest', status: undefined }), true)
})

test('manifest node with "unknown" status shows banner (R30 regression case)', () => {
  assert.equal(showNotMonitoredBanner({ source: 'manifest', status: 'unknown' }), true)
})

test('manifest node with "healthy" but NO metrics still shows banner', () => {
  assert.equal(showNotMonitoredBanner({ source: 'manifest', status: 'healthy' }), true)
})

test('manifest node with "healthy" AND live metrics hides banner', () => {
  assert.equal(showNotMonitoredBanner({ source: 'manifest', status: 'healthy', metrics: { latency_ms: 200 } }), false)
})

test('manifest node with null metric values still shows banner', () => {
  assert.equal(showNotMonitoredBanner({ source: 'manifest', metrics: { latency_ms: null } }), true)
})

test('manifest node with note-only metrics still shows banner', () => {
  assert.equal(showNotMonitoredBanner({ source: 'manifest', metrics: { note: 'info' } }), true)
})

test('manifest node with only internal _fields still shows banner', () => {
  assert.equal(showNotMonitoredBanner({ source: 'manifest', metrics: { _last_poll: 1234, _check_description: 'probe' } }), true)
})

test('discovery node does NOT show banner', () => {
  assert.equal(showNotMonitoredBanner({ source: 'discovery', status: 'healthy' }), false)
})

test('node without source does NOT show banner', () => {
  assert.equal(showNotMonitoredBanner({ status: 'unknown' }), false)
})

// --- Live metrics panel tests (shows when HAS live metrics) ---

test('manifest node with live metrics shows metrics panel', () => {
  assert.equal(showLiveMetrics({ source: 'manifest', metrics: { latency_ms: 200 } }), true)
})

test('manifest node without metrics hides metrics panel', () => {
  assert.equal(showLiveMetrics({ source: 'manifest' }), false)
})

test('manifest node with all-null metrics hides metrics panel', () => {
  assert.equal(showLiveMetrics({ source: 'manifest', metrics: { latency_ms: null } }), false)
})

test('discovery node never shows manifest metrics panel', () => {
  assert.equal(showLiveMetrics({ source: 'discovery', metrics: { latency_ms: 200 } }), false)
})

// --- AI Analysis tests ---

test('manifest node hides AI analysis', () => {
  assert.equal(showAIAnalysis({ source: 'manifest', status: 'not monitored' }, false), false)
})

test('manifest node with live metrics still hides AI analysis', () => {
  assert.equal(showAIAnalysis({ source: 'manifest', status: 'healthy', metrics: { latency_ms: 200 } }, false), false)
})

test('discovery node shows AI analysis', () => {
  assert.equal(showAIAnalysis({ source: 'discovery', status: 'healthy' }, false), true)
})

test('demo mode hides AI analysis for all nodes', () => {
  assert.equal(showAIAnalysis({ source: 'discovery', status: 'healthy' }, true), false)
})

// --- Logs button tests ---

test('manifest node shows disabled logs (REQ-202 not yet implemented)', () => {
  assert.equal(showLogsDisabled({ source: 'manifest', status: 'not monitored' }), true)
})

test('manifest node with live metrics still disables logs (REQ-202 pending)', () => {
  assert.equal(showLogsDisabled({ source: 'manifest', status: 'healthy', metrics: { latency_ms: 200 } }), true)
})

test('discovery node shows enabled logs', () => {
  assert.equal(showLogsDisabled({ source: 'discovery', status: 'healthy' }), false)
})

console.log('\nDone.')
