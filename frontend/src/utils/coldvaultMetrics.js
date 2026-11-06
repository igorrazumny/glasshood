// File: frontend/src/utils/coldvaultMetrics.js
// Purpose: Plain line for ColdVault metrics that were not read (REQ-GHA-025 clause 5)

// status: {read, reason, checked_at (epoch s)} from /api/topology
export function metricsNotRead(status) {
  const at = status.checked_at
    ? ` · ${new Date(status.checked_at * 1000).toISOString().slice(11, 16)} UTC`
    : ''
  return `ColdVault metrics not read: ${status.reason || 'unknown reason'}${at}`
}

