// File: frontend/src/utils/boxBasis.js
// Purpose: REQ-GHA-044 clause 3: what a box's state is based on, in plain words.

const BY_PROBE = {
  http: 'Answers at its address',
  azure_resource: 'Provider reports its state',
  gcp_resource: 'Provider reports its state',
  aws_ecs_service: 'Provider reports its state',
  aws_load_balancer: 'Provider reports its state',
  aws_target_group: 'Provider reports its state',
  aws_log_group: 'Provider reports its state',
  statuspage: "Provider's public status page",
  glasshood_self: "GlassHood's own record of this work",
  coldvault_models: "ColdVault's record of its model calls",
  mcp_attestation: 'Attestation check answered',
}
const NOT_CHECKED = new Set(['not checked', 'not monitored', 'unknown', 'stale'])
const NOT_IN_USE = new Set(['planned', 'disabled', 'deployed'])

export function boxBasis(node) {
  const m = node?.metrics || {}
  if (NOT_IN_USE.has(node?.status)) return 'Set up but not in use'
  if (NOT_CHECKED.has(node?.status)) {
    const why = m._check_description || m.note
    return why ? `Not checked: ${why}` : 'Not checked'
  }
  if (BY_PROBE[m._probe_type]) return BY_PROBE[m._probe_type]
  if (Object.keys(m).some(k => !k.startsWith('_') && k !== 'note')) return 'Measurements read'
  return m._check_description || 'Not checked'
}
