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
  gcp_compute: { causes: ['The machine may be stopped, restarting or failing.'],
    action: 'Infrastructure owner: check the instance status and recent operations in Google Cloud.' },
  gcp_asset: { causes: ['The resource may have been changed, renamed or removed.'],
    action: 'Infrastructure owner: confirm the resource still exists in Google Cloud and review its recent changes.' },
  gcp_backend_health: { causes: ['The application may not be answering its health check.', 'A recent deployment may have replaced the instance.'],
    action: 'Service owner: read the health state of each backend in Google Cloud, then the application logs from that time.' },
  gcp_sql_backup: { causes: ['The latest backup may have failed or may not have run.'],
    action: 'Database owner: check the backup history of this database and run a backup if the latest is missing.' },
  gcp_secret_count: { causes: ['A secret may have been added, removed or left without a version.'],
    action: 'Security owner: review the recent changes to these secrets in Google Cloud.' },
  coldvault_models: { causes: ['The AI provider may be down, rate limiting or out of quota.'],
    action: 'Service owner: read which model failed above and check that provider status and its quota.' },
}

// GlassHood's own work: the check says exactly which task failed and why
const BY_OWN_RESULT = [
  [/limit|daily cap|model calls|blocked/i, {
    impact: 'Checks and alarms keep running. New AI evaluations and AI log reviews have stopped until this is resolved.',
    causes: ['Many evaluations or restarts may have used up the AI allowance.'],
    action: 'GlassHood administrator: see the spending line in the AI overview panel. If this use was expected, raise the limit; otherwise find what caused the extra calls. Evaluations restart by themselves once the limit allows them.' }],
  [/not saved|saving/i, {
    impact: 'Monitoring continues, but alarms and reports would be lost at the next restart.',
    causes: ['The storage share may be unavailable or read-only.'],
    action: 'GlassHood administrator: check that the state storage share is mounted and writable on the container app.' }],
  [/figures were not read/i, {
    causes: ['GlassHood may not have obtained its identity token.', 'ColdVault may have refused or not answered the request.'],
    action: 'GlassHood administrator: read the reason above, then check the identity setup and the ColdVault metrics address.' }],
  [/status pages? could not be read/i, {
    causes: ['The provider status page may be unavailable or may have changed.'],
    action: 'GlassHood administrator: open the provider status pages directly and compare them with what GlassHood reads.' }],
  [/AI overview|AI log review/i, {
    causes: ['The AI provider may have failed or refused the call.', 'A recent restart may have interrupted the work.'],
    action: 'GlassHood administrator: read the reason above and the backend log around that time, then check the AI provider and its key.' }],
  [/late|stopped|not run/i, {
    causes: ['This background task may have stopped.', 'A recent restart may have interrupted it.'],
    action: 'GlassHood administrator: read the backend log for this task around its last run; restart the app if the task has stopped.' }],
]
const OWN_DEFAULT = { causes: [], action: 'GlassHood administrator: read the result above and the backend log around that time.' }

function guidance(check) {
  if (check?.probe_type !== 'glasshood_self') return BY_CHECK[check?.probe_type] || null
  return BY_OWN_RESULT.find(([pattern]) => pattern.test(check.result || ''))?.[1] || OWN_DEFAULT
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
  const known = guidance(alert.check)
  if (known) return known.action
  const msg = (alert.message || '').toLowerCase()
  const hit = BY_METRIC.find(([pattern]) => pattern.test(msg))
  return hit ? hit[1] : 'Service owner: start from what the check found above, then check this part and what it depends on.'
}

export function ruleReport(alert) {
  const part = alert.part_label || alert.node_label || 'This part'
  const check = alert.check || null
  const first = alert.first_seen || alert.triggered_at
  const last = alert.last_seen || first
  const numeric = alert.metric_value != null
  const unreadable = check?.status === 'not checked'
  const own = unreadable ? null : guidance(check)
  const impact = own?.impact || (unreadable
    ? `GlassHood could not read ${part}, so its state is unknown. This is not evidence that the service is down.`
    : numeric
      ? `A measured value for ${part} is past its threshold. This does not show that the service is unavailable, and the effect on users is not known from this check.`
      : `This check failed for ${part}. Whether users are affected is not known from this check alone.`)
  const signal = check?.result
    || (numeric ? `${alert.metric_name}: ${alert.metric_value}${alert.threshold != null ? ` (threshold ${alert.threshold})` : ''}.` : null)
    || 'The check recorded no further detail; the cause is not known.'
  const timing = !first ? 'The first observation time is unavailable.'
    : last !== first ? `Observed since ${dateTime(first)}; last checked ${dateTime(last)}.`
      : `First observed ${dateTime(first)}.`
  const causes = unreadable ? UNREADABLE.causes : (own?.causes || [])
  return { title: alert.title || alert.message || 'A monitored check failed', impact, signal, timing, causes, action: ruleAction(alert) }
}
