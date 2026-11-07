// File: frontend/src/components/AlertDetailModal.jsx
// Purpose: Detail modal for alerts — full info, correlation context, acknowledge button

import { useState, useEffect } from 'react'
import { X, AlertTriangle, AlertOctagon, Info, CheckCircle, Shield } from 'lucide-react'
import { apiFetch } from '../utils/api'
import { alarmTitle, alarmWhen, alarmKindLabel, alarmTag, alarmRef } from '../utils/alarms'
import InvestigationPanel from './InvestigationPanel'
import { dateTime } from '../utils/time'

// REQ-009: severity styles pair light (bg-100 + text-700 + border-300) with
// dark (bg-500/10 + text-400 + border-500/30) so the icon + badge read on
// both themes.
const SEVERITY_STYLE = {
  critical: { icon: AlertOctagon,
    color: 'text-red-700 dark:text-red-400',
    bg: 'bg-red-100 dark:bg-red-500/10',
    border: 'border-red-300 dark:border-red-500/30' },
  warning: { icon: AlertTriangle,
    color: 'text-yellow-700 dark:text-yellow-400',
    bg: 'bg-yellow-100 dark:bg-yellow-500/10',
    border: 'border-yellow-300 dark:border-yellow-500/30' },
  info: { icon: Info,
    color: 'text-blue-700 dark:text-blue-400',
    bg: 'bg-blue-100 dark:bg-blue-500/10',
    border: 'border-blue-300 dark:border-blue-500/30' },
}

function recommendAction(alert) {
  const msg = (alert.message || '').toLowerCase()
  const rule = (alert.rule_id || '').toLowerCase()
  if (rule.startsWith('correlated:')) return 'Investigate data integrity — correlated operational + statistical anomaly detected'
  if (rule.startsWith('anomaly')) return 'Statistical anomaly detected in infrastructure metrics. The system identified a significant deviation from the established baseline. Check the anomaly details in the right panel for z-score, confidence level, and baseline comparison. If the anomaly persists across multiple polling cycles, investigate the underlying infrastructure component.'
  if (msg.includes('cpu')) return 'Scale up VM or investigate high-CPU process'
  if (msg.includes('latency') || msg.includes('slow')) return 'Check load balancer and backend health'
  if (msg.includes('error') || msg.includes('fail')) return 'Investigate error spike in application logs'
  if (msg.includes('cve') || msg.includes('vulnerab')) return 'Check CVE patch status and apply updates'
  if (msg.includes('disk')) return 'Free disk space or expand volume'
  if (msg.includes('memory') || msg.includes('ram')) return 'Investigate memory leak or scale instance'
  if (msg.includes('disconnected') || msg.includes('offline')) return 'Check network connectivity and service health'
  if (alert.severity === 'critical') return 'Investigate immediately — critical severity'
  if (alert.severity === 'warning') return 'Monitor closely and investigate if condition persists'
  return 'Review alert details and take appropriate action'
}

export default function AlertDetailModal({ alert, onClose, currentUser = '' }) {
  const [acking, setAcking] = useState(false)
  const [acked, setAcked] = useState(false)
  const [ackError, setAckError] = useState(null)
  // REQ-GHA-029: the alarm read fresh (its saved report) and whether this user may act on it
  const [fresh, setFresh] = useState(null)

  useEffect(() => {
    setAcked(alert?.acknowledged || false)
    setAckError(null)
    setFresh(null)
    if (!alert) return
    const ref = alarmRef(alert)
    const q = new URLSearchParams({ group: ref.group, ...(ref.node_id ? { node_id: ref.node_id } : {}) })
    apiFetch(`/api/alerts/one?${q}`).then(setFresh).catch(() => {})
  }, [alert])

  if (!alert) return null
  const canAct = fresh ? fresh.can_act : null  // null: not known yet
  const ex = (fresh || alert).explanation  // REQ-GHA-031

  const style = SEVERITY_STYLE[alert.severity] || SEVERITY_STYLE.info
  const Icon = style.icon
  const isCorrelated = (alert.rule_id || '').startsWith('correlated:')
  const isAnomaly = (alert.rule_id || '').startsWith('anomaly')
  // REQ-004: per-alert classification snapshot recorded at alert creation
  // by the rules engine. Falls back to null when missing — the standard
  // alert layout below renders without classification panels in that case.
  const ac = alert.anomaly_classification || null

  const handleAck = () => {
    setAcking(true)
    setAckError(null)
    apiFetch('/api/alerts/ack', {
      method: 'POST',
      body: JSON.stringify({ rule_id: alarmRef(alert).group, node_id: alert.node_id || null }),
    })
      .then(() => setAcked(true))
      .catch(err => setAckError(err.message || 'Failed to acknowledge'))
      .finally(() => setAcking(false))
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={onClose}>
      <div className="absolute inset-0 bg-black/40 dark:bg-black/60" />
      <div
        className="relative bg-card dark:bg-purple-800 border border-border dark:border-purple-700 rounded-xl p-5 max-w-lg w-full mx-4 max-h-[85vh] overflow-y-auto"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Icon size={18} className={style.color} />
            <span className={`text-xs font-bold uppercase px-2 py-0.5 rounded ${style.bg} ${style.color}`}>
              {alert.severity}
            </span>
            {/* REQ-009 round-6 fix: `purple` in tailwind.config is renamed
                to ColdVault's blue scale, so the original `bg-purple-100`
                read as light-blue and collapsed visual distinction from
                severity colors. Use Tailwind's stock `indigo` (untouched
                by REQ-010) so the badge stays semantically purple-ish. */}
            {alarmTag(alert) && (
              <span className="text-xs font-bold uppercase px-2 py-0.5 rounded border border-gray-400 dark:border-purple-400 text-gray-600 dark:text-purple-200">
                {alarmTag(alert)}
              </span>
            )}
            {isCorrelated && (
              <span className="text-xs font-bold uppercase px-2 py-0.5 rounded bg-indigo-100 dark:bg-indigo-500/20 text-indigo-700 dark:text-indigo-300">
                Correlated
              </span>
            )}
          </div>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-800 dark:text-purple-300 dark:hover:text-white transition-colors">
            <X size={18} />
          </button>
        </div>

        {/* REQ-GHA-027 clause 5: the plain line first; rule names and metric=value are
            only in the technical details below */}
        <p className="text-sm text-gray-800 dark:text-purple-100 leading-relaxed">{alarmTitle(alert)}</p>
        <p className="text-xs text-gray-500 dark:text-purple-300 mb-4">
          {alert.part_label ? `${alert.part_label} · ` : ''}{alarmWhen(alert)}
        </p>
        {/* REQ-GHA-028 clause 4 */}
        {alarmKindLabel(alert) && (
          <p className="text-xs text-gray-500 dark:text-purple-300 -mt-3 mb-4">
            {alarmKindLabel(alert) === 'example'
              ? 'Example: shown to illustrate monitoring; not yet a trusted alarm.'
              : 'Observation about the setup; not an outage.'}
          </p>
        )}
        {alert.kind === 'ai' && (
          <p className="text-xs text-gray-500 dark:text-purple-300 -mt-3 mb-4">
            Found by the AI review of the logs.{alert.severity === 'critical'
              ? ' A critical one stays until someone acknowledges it.' : ' It ends when the review no longer sees it.'}
          </p>
        )}
        {/* REQ-GHA-031: what is happening and where to look, in plain words, before any log line */}
        {alert.kind === 'ai' && ex?.what && (
          <div className="space-y-3 mb-3">
            <div className={`rounded-lg p-3 ${style.bg} border ${style.border}`}>
              <span className="text-xs font-semibold text-gray-500 dark:text-purple-300 uppercase">What is happening</span>
              <p className="text-sm text-gray-800 dark:text-purple-100 mt-1 leading-relaxed">{ex.what}</p>
            </div>
            {(ex.suspicion || ex.directions?.length > 0) && (
              <div className="rounded-lg p-3 bg-surface dark:bg-purple-900/50 border border-border dark:border-purple-700">
                <span className="text-xs font-semibold text-gray-500 dark:text-purple-300 uppercase">Where to look</span>
                {ex.suspicion && (
                  <p className="text-sm text-gray-700 dark:text-purple-100 mt-1 leading-relaxed">
                    <strong>Main suspicion:</strong> {ex.suspicion}
                  </p>
                )}
                {ex.directions?.length > 0 && (
                  <ul className="mt-1 space-y-0.5">
                    {ex.directions.map((d, i) => (
                      <li key={i} className="text-sm text-gray-700 dark:text-purple-100 flex items-start gap-2">
                        <span className="text-gray-500 dark:text-purple-300">{'>'}</span><span>{d}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>
        )}

        {/* Anomaly alerts: rich classified presentation */}
        {isAnomaly && ac ? (
          <div className="space-y-3 mb-4">
            {/* Classification badge */}
            <div className={`rounded-lg p-3 ${style.bg} border ${style.border}`}>
              <span className="text-xs font-semibold text-gray-500 dark:text-purple-300 uppercase">Pattern Identified</span>
              <p className={`text-base font-bold mt-1 ${style.color}`}>{ac.classification}</p>
            </div>

            {/* Business impact */}
            <div className="rounded-lg p-3 bg-surface dark:bg-purple-900/50 border border-border dark:border-purple-700">
              <span className="text-xs font-semibold text-gray-500 dark:text-purple-300 uppercase">What This Means</span>
              <p className="text-sm text-gray-700 dark:text-purple-100 mt-1 leading-relaxed">{ac.business_impact}</p>
            </div>

            {/* Metric details — plain language */}
            {ac.details && ac.details.length > 0 && (
              <div className="rounded-lg p-3 bg-surface dark:bg-purple-900/50 border border-border dark:border-purple-700">
                <span className="text-xs font-semibold text-gray-500 dark:text-purple-300 uppercase">Affected Metrics</span>
                {ac.details.map((d, i) => (
                  <div key={i} className="mt-2 text-sm">
                    <p className="text-gray-800 dark:text-purple-100 font-medium">{d.summary}</p>
                    {d.what_it_means && <p className="text-gray-500 dark:text-purple-300 text-xs mt-0.5">{d.what_it_means}</p>}
                  </div>
                ))}
              </div>
            )}

            {/* Recommended actions — by role */}
            <div className="rounded-lg p-3 bg-surface dark:bg-purple-900/50 border border-border dark:border-purple-700">
              <span className="text-xs font-semibold text-gray-500 dark:text-purple-300 uppercase">Recommended Actions</span>
              <ul className="mt-1 space-y-1">
                {ac.actions.map((action, i) => (
                  <li key={i} className="text-sm text-gray-700 dark:text-purple-100 flex items-start gap-2">
                    <span className="text-gray-500 dark:text-purple-300 mt-0.5">{'>'}</span>
                    <span>{action}</span>
                  </li>
                ))}
              </ul>
            </div>

            {/* Technical details — collapsible */}
            <details className="rounded-lg bg-surface dark:bg-purple-900/50 border border-border dark:border-purple-700">
              <summary className="p-3 text-xs font-semibold text-gray-500 dark:text-purple-300 uppercase cursor-pointer hover:text-gray-700 dark:hover:text-purple-200">
                Technical Details
              </summary>
              <div className="px-3 pb-3 space-y-1">
                {ac.details && ac.details.map((d, i) => (
                  <div key={i} className="flex items-center justify-between text-xs font-mono text-gray-600 dark:text-purple-200">
                    <span>{d.name}</span>
                    <span>{d.value?.toFixed?.(1) ?? d.value} (baseline: {d.baseline?.toFixed?.(1) ?? d.baseline}, z: {typeof d.z_score === 'number' ? d.z_score.toFixed?.(1) : d.z_score})</span>
                  </div>
                ))}
                <div className="flex items-center justify-between text-xs text-gray-500 dark:text-purple-300 mt-2">
                  <span>Rule ID</span>
                  <span className="font-mono">{alert.rule_id}</span>
                </div>
                <div className="flex items-center justify-between text-xs text-gray-500 dark:text-purple-300">
                  <span>First seen</span>
                  <span>{dateTime(alert.first_seen) || '-'}</span>
                </div>
              </div>
            </details>
          </div>
        ) : (
          /* Standard (non-anomaly) alert layout */
          <div className="space-y-3 mb-4">
            {/* Metric value vs threshold */}
            {alert.metric_value != null && (
              <div className={`rounded-lg p-3 ${style.bg} border ${style.border}`}>
                <div className="flex items-center justify-between text-sm">
                  <span className="text-gray-500 dark:text-purple-300">Current value</span>
                  <span className={`font-bold ${style.color}`}>{alert.metric_value}</span>
                </div>
                {alert.threshold != null && (
                  <div className="flex items-center justify-between text-sm mt-1">
                    <span className="text-gray-500 dark:text-purple-300">Threshold</span>
                    <span className="text-gray-700 dark:text-purple-100">{alert.threshold}</span>
                  </div>
                )}
              </div>
            )}

            {/* Correlation context — uses indigo for the same reason as the
                badge above (the renamed `purple` scale would render as blue). */}
            {isCorrelated && (
              <div className="rounded-lg p-3 bg-indigo-50 dark:bg-indigo-500/10 border border-indigo-300 dark:border-indigo-500/30">
                <div className="flex items-center gap-2 mb-1">
                  <Shield size={14} className="text-indigo-700 dark:text-indigo-300" />
                  <span className="text-xs font-semibold text-indigo-700 dark:text-indigo-300 uppercase">Data Integrity Risk</span>
                </div>
                <p className="text-xs text-gray-700 dark:text-purple-100 leading-relaxed">
                  This alert was generated by the correlation engine. An operational alert and a statistical
                  anomaly occurred simultaneously, suggesting a potential data integrity compromise.
                  Investigate both the operational issue and the anomalous metric.
                </p>
              </div>
            )}

            {/* REQ-GHA-029/031: the log lines the AI review saw, the evidence, closed by default */}
            {alert.evidence?.length > 0 && (
              <details className="rounded-lg bg-surface dark:bg-purple-900/50 border border-border dark:border-purple-700">
                <summary className="p-3 text-xs font-semibold text-gray-500 dark:text-purple-300 uppercase cursor-pointer hover:text-gray-700 dark:hover:text-purple-200">
                  View the related log entries ({alert.evidence.length})
                </summary>
                <div className="px-3 pb-3">
                  {/* REQ-GHA-030 clause 2: quoted lines keep their own time, which is UTC */}
                  <p className="text-[11px] text-gray-500 dark:text-purple-300">Times in these log lines are UTC.</p>
                  {alert.evidence.map((e, i) => (
                    <p key={i} className="text-[11px] font-mono text-gray-600 dark:text-purple-200 break-words mt-1">{e}</p>
                  ))}
                </div>
              </details>
            )}

            {/* Recommended action */}
            {alert.kind !== 'ai' && (
              <div className="rounded-lg p-3 bg-surface dark:bg-purple-900/50 border border-border dark:border-purple-700">
                <span className="text-xs font-semibold text-gray-500 dark:text-purple-300 uppercase">Recommended Action</span>
                <p className="text-sm text-gray-700 dark:text-purple-100 mt-1">{recommendAction(alert)}</p>
              </div>
            )}

            {/* Technical details — collapsible ("Details" on an AI alarm, REQ-GHA-031) */}
            <details className="rounded-lg bg-surface dark:bg-purple-900/50 border border-border dark:border-purple-700">
              <summary className="p-3 text-xs font-semibold text-gray-500 dark:text-purple-300 uppercase cursor-pointer hover:text-gray-700 dark:hover:text-purple-200">
                {alert.kind === 'ai' ? 'Details' : 'Technical Details'}
              </summary>
              <div className="px-3 pb-3 space-y-1 text-xs text-gray-600 dark:text-purple-200">
                {(alert.reasons?.length ? alert.reasons : [alert.message]).map((r, i) => (
                  <p key={i} className="font-mono break-words">{r}</p>
                ))}
                <div className="flex items-center justify-between text-gray-500 dark:text-purple-300 mt-2">
                  <span>Rule ID</span>
                  <span className="font-mono">{alert.rule_id}</span>
                </div>
                {alert.node_id && (
                  <div className="flex items-center justify-between text-gray-500 dark:text-purple-300">
                    <span>Part</span>
                    <span className="font-mono">{alert.node_id}</span>
                  </div>
                )}
                {alert.metric_name && (
                  <div className="flex items-center justify-between text-gray-500 dark:text-purple-300">
                    <span>Metric</span>
                    <span className="font-mono">{alert.metric_name}</span>
                  </div>
                )}
              </div>
            </details>
          </div>
        )}

        {/* REQ-GHA-029: Investigate deeper, the saved report and its follow-ups */}
        <InvestigationPanel alert={fresh || alert} canAct={canAct === true} />

        {/* Acknowledge button (operators; a viewer sees who acknowledged) */}
        {acked ? (
          <div className="flex items-center gap-2 text-green-700 dark:text-green-400 text-sm py-2">
            <CheckCircle size={16} />
            <span>Acknowledged{alert.acknowledged_by ? ` by ${alert.acknowledged_by}` : ''}</span>
          </div>
        ) : canAct === false ? null : (
          <button
            onClick={handleAck}
            disabled={acking}
            className="w-full py-2 rounded-lg bg-blue-600 hover:bg-blue-500 disabled:bg-gray-200 dark:disabled:bg-purple-700 disabled:text-gray-400 dark:disabled:text-purple-300 text-white text-sm font-medium transition-colors"
          >
            {acking ? 'Acknowledging...' : 'Acknowledge Alert'}
          </button>
        )}
        {ackError && <p className="text-xs text-red-700 dark:text-red-400 mt-1">{ackError}</p>}
      </div>
    </div>
  )
}
