// File: frontend/src/utils/coldvaultMetrics.js
// Purpose: Plain line for ColdVault metrics that were not read (REQ-GHA-025 clause 5),
// timed in the reader's zone (REQ-GHA-030)

import { clock } from './time.js'

// status: {read, reason, checked_at (epoch s)} from /api/topology
export function metricsNotRead(status) {
  const at = status.checked_at
    ? ` · ${clock(status.checked_at * 1000)}`
    : ''
  return `ColdVault metrics not read: ${status.reason || 'unknown reason'}${at}`
}

