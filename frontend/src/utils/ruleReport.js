// File: frontend/src/utils/ruleReport.js
// Purpose: REQ-GHA-031 (amended 2026-11-08) — the report of a rule or status alarm, built only
// from what the check observed. Causes are possibilities, impact is stated only if evidenced.

import { dateTime } from './time.js'

const UNREADABLE = {
  causes: ["GlassHood's read access to this part may have changed or expired.",
    "The provider's own API may have been unavailable when GlassHood asked.",
    'The part may have been renamed or removed.'],
  action: "Monitoring owner: confirm GlassHood's read access to this part, then whether the part still exists under this name.",
}

// by the kind of check that failed: a load balancer problem does not call for opening a health URL
const BY_CHECK = {
  http: { causes: ['The application may be down or failing behind this address.', 'The address may redirect or may have changed.', 'A network or edge layer in front of the application may be refusing the request.'],
    action: 'Service owner: open this address directly and confirm a successful response without a redirect, then compare with the load balancer and application checks.' },
  aws_load_balancer: { causes: ['The load balancer may be provisioning or may have failed in AWS.'],
    action: 'Infrastructure owner: check the load balancer state and recent changes in the AWS console.' },
  aws_target_group: { causes: ['The application may not be answering its health path.', 'A recent deployment may have replaced the running task.'],
    action: 'Service owner: read the reason AWS gives for each unhealthy target, then the application logs from that time.' },
  aws_ecs_service: { causes: ['Tasks may be crashing at startup.', 'A deployment may have failed.', 'AWS may not have had capacity to start a replacement task.'],
    action: 'Service owner: read the ECS service events and the stop reason of the latest task.' },
  aws_log_group: { causes: ['The log group may have been removed or renamed.'],
    action: 'Monitoring owner: confirm that the log group still exists under the configured name.' },
  azure_resource: { causes: ['The resource may be provisioning, stopped or failed in Azure.'],
    action: 'Infrastructure owner: check the resource state and its activity log in Azure.' },
}

const BY_METRIC = [
  [/cpu/, 'Check recent CPU use and workload changes; scale only if the resource is sustaining user-visible demand.'],
  [/latency|slow/, 'Compare response time at the entry point with the application and its dependencies to find where delay begins.'],
  [/cve|vulnerab/, 'Review the affected package and patch guidance with the service owner before changing the deployed image.'],
  [/disk/, 'Check free space and recent growth, then identify what is consuming storage before cleanup or expansion.'],
  [/memory|ram/, 'Review memory use and recent workload changes; check for sustained growth before resizing or restarting.'],
  [/disconnected|offline/, 'Check connectivity from the caller through the immediate dependency and confirm whether the service is reachable.'],
]

export function ruleAction(alert) {
  const rule = (alert.rule_id || '').toLowerCase()
  if (rule.startsWith('correlated:')) return 'Investigate data integrity — correlated operational + statistical anomaly detected'
  if (rule.startsWith('anomaly')) return 'Statistical anomaly detected in infrastructure metrics. The system identified a significant deviation from the established baseline. Check the anomaly details in the right panel for z-score, confidence level, and baseline comparison. If the anomaly persists across multiple polling cycles, investigate the underlying infrastructure component.'
  if (alert.check?.status === 'not checked') return UNREADABLE.action
  const known = BY_CHECK[alert.check?.probe_type]
  if (known) return known.action
  const msg = (alert.message || '').toLowerCase()
  const hit = BY_METRIC.find(([pattern]) => pattern.test(msg))
  return hit ? hit[1] : 'Check this part and what it depends on; this check gives no more specific direction.'
}

export function ruleReport(alert) {
  const part = alert.part_label || alert.node_label || 'This part'
  const check = alert.check || null
  const first = alert.first_seen || alert.triggered_at
  const last = alert.last_seen || first
  const numeric = alert.metric_value != null
  const unreadable = check?.status === 'not checked'
  const impact = unreadable
    ? `GlassHood could not read ${part}, so its state is unknown. This is not evidence that the service is down.`
    : numeric
      ? `A measured value for ${part} is past its threshold. This does not show that the service is unavailable, and the effect on users is not known from this check.`
      : `This check failed for ${part}. Whether users are affected is not known from this check alone.`
  const signal = check?.result
    || (numeric ? `${alert.metric_name}: ${alert.metric_value}${alert.threshold != null ? ` (threshold ${alert.threshold})` : ''}.` : null)
    || 'The check recorded no further detail; the cause is not known.'
  const timing = !first ? 'The first observation time is unavailable.'
    : last !== first ? `Observed since ${dateTime(first)}; last checked ${dateTime(last)}.`
      : `First observed ${dateTime(first)}.`
  const causes = unreadable ? UNREADABLE.causes : (BY_CHECK[check?.probe_type]?.causes || [])
  return { title: alert.title || alert.message || 'A monitored check failed', impact, signal, timing, causes, action: ruleAction(alert) }
}
