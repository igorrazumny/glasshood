// File: frontend/src/components/NodeDetailModal.jsx
// Purpose: Modal popup for detailed node inspection — metrics + diagnostics + AI analysis

import { useEffect, useState, useCallback } from 'react'
import { X, FileText, Brain, AlertTriangle, CheckCircle, RefreshCw, Clock, Cpu } from 'lucide-react'
import { apiFetch } from '../utils/api'
import { canRecheck, describeRecheck, recheckError, PARTNER_NOTE, WAKE_NOTE } from '../utils/mcpRecheck'
import { overviewStamp, isStale } from '../utils/overview.js'
import { clock } from '../utils/time'
import { boxBasis } from '../utils/boxBasis'
import { noLogsReason } from '../utils/logsView'
import LogViewerModal from './LogViewerModal'

const STATUS_COLORS = {
  healthy: '#22c55e',
  degraded: '#eab308',
  error: '#ef4444',
  disconnected: '#4b5563',
  unknown: '#6b7280',
}

// Check if a manifest node has live metric values (not just internal metadata)
function _hasLiveMetrics(node) {
  if (!node.metrics) return false
  const metricKeys = Object.keys(node.metrics).filter(k => !k.startsWith('_') && k !== 'note')
  return metricKeys.length > 0 && metricKeys.some(k => node.metrics[k] !== null)
}

// REQ-009: status pills get light + dark variants. Light pills use bg-color-100
// on text-color-700 for readable contrast on the white card; dark pills keep
// the original /10 alpha + light text.
const STATUS_BG = {
  healthy: 'bg-green-100 text-green-700 dark:bg-green-500/10 dark:text-green-400',
  degraded: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-500/10 dark:text-yellow-400',
  error: 'bg-red-100 text-red-700 dark:bg-red-500/10 dark:text-red-400',
  disconnected: 'bg-gray-100 text-gray-600 dark:bg-gray-500/10 dark:text-gray-400',
  unknown: 'bg-gray-100 text-gray-600 dark:bg-gray-500/10 dark:text-gray-400',
}

function timeAgo(timestamp) {
  if (!timestamp) return null
  const seconds = Math.floor(Date.now() / 1000 - timestamp)
  if (seconds < 60) return 'just now'
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
  return `${Math.floor(seconds / 86400)}d ago`
}

function _formatAge(seconds) {
  if (seconds < 0) return 'just now'
  if (seconds < 60) return `${seconds}s ago`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
  return `${Math.floor(seconds / 86400)}d ago`
}

export default function NodeDetailModal({ node, onClose, isDemo, hideCosts }) {
  const [showLogs, setShowLogs] = useState(false)
  const [nodeAnalysis, setNodeAnalysis] = useState(null)
  const [tick, setTick] = useState(0)
  // REQ-GHA-020: Recheck via MCP (on demand only; result kept in this modal, not stored)
  const [partner, setPartner] = useState(false)
  const [rechecking, setRechecking] = useState(false)
  const [recheck, setRecheck] = useState(null)

  // Tick every second for live timer
  useEffect(() => {
    const id = setInterval(() => setTick(t => t + 1), 1000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  // REQ-GHA-024: read this part's overview from the cache, and again every minute while the
  // modal is open, so a newly written overview appears. Reading never triggers the model.
  const [now, setNow] = useState(Date.now())
  const [readError, setReadError] = useState('')
  useEffect(() => {
    if (!node || isDemo) return
    const load = () => apiFetch(`/api/analysis/node/${node.id}`)
      .then(a => { setNodeAnalysis(a); setReadError('') })
      // A failed read keeps the overview already shown and says why (clause 7).
      .catch(e => setReadError(`Could not reload this overview (${e?.message || 'network error'})`))
    load()
    const t = setInterval(() => { setNow(Date.now()); load() }, 60000)
    return () => clearInterval(t)
  }, [node?.id, isDemo])
  const overviewStale = isStale(nodeAnalysis, now)

  const handleRecheck = useCallback(() => {
    if (!node || rechecking) return
    setRechecking(true)
    setRecheck(null)
    apiFetch(`/api/mcp-recheck/${node.id}`, {
      method: 'POST',
      body: JSON.stringify({ mode: partner ? 'partner' : 'vault' }),
    })
      .then(r => setRecheck({ ok: r.ok, text: describeRecheck(r) }))
      .catch(e => setRecheck({ ok: false, text: recheckError(e) }))
      .finally(() => setRechecking(false))
  }, [node, rechecking, partner])

  if (!node) return null

  const statusColor = STATUS_COLORS[node.status] || STATUS_COLORS.unknown
  const statusBg = STATUS_BG[node.status] || STATUS_BG.unknown
  const analysisAge = timeAgo(nodeAnalysis?.analyzed_at)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={onClose}>
      {/* REQ-009: backdrop slightly darker on light theme so the modal pops. */}
      <div className="absolute inset-0 bg-black/40 dark:bg-black/60" />
      <div
        className="relative bg-card dark:bg-purple-800 border border-border dark:border-purple-700 rounded-xl p-5 max-w-lg w-full mx-4 max-h-[85vh] overflow-y-auto"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <div className="w-3 h-3 rounded-full" style={{ backgroundColor: statusColor }} />
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white">{node.label}</h2>
            <span className={`text-xs px-2 py-0.5 rounded font-medium ${statusBg}`}>
              {node.status}
            </span>
          </div>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-800 dark:text-purple-300 dark:hover:text-white transition-colors">
            <X size={18} />
          </button>
        </div>

        {/* Cost (REQ-215: hidden when role !== admin) */}
        {!hideCosts && node.cost_yearly_usd != null && node.cost_yearly_usd > 0 && (
          <div className="mb-3 text-sm font-mono">
            <span className={node.status === 'disabled' ? 'text-gray-500 dark:text-purple-300' : 'text-green-600 dark:text-green-400'}>
              ${node.cost_yearly_usd.toLocaleString()}/yr
            </span>
            <span className="text-gray-500 dark:text-purple-300 ml-2">
              (~${Math.round(node.cost_yearly_usd / 12).toLocaleString()}/mo)
            </span>
          </div>
        )}

        {/* Metrics — skip for manifest nodes with live metrics (shown in dedicated panel below) */}
        {!(node.source === 'manifest' && _hasLiveMetrics(node)) && node.metrics && Object.keys(node.metrics).length > 0 && (
          <div className="mb-4">
            <h3 className="text-xs font-semibold text-gray-500 dark:text-purple-300 uppercase tracking-wider mb-2">Metrics</h3>
            <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
              {Object.entries(node.metrics).filter(([k]) => !k.startsWith('_')).map(([k, v]) => (
                <div key={k} className="text-sm">
                  <span className="text-gray-500 dark:text-purple-300">{k}: </span>
                  <span className="text-gray-700 dark:text-purple-100">
                    {v === null ? '-' : typeof v === 'object' ? JSON.stringify(v) : String(v)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Diagnostics */}
        {node.diagnostics && (
          <div>
            <h3 className="text-xs font-semibold text-gray-500 dark:text-purple-300 uppercase tracking-wider mb-2">Diagnostics</h3>
            <pre className="bg-surface dark:bg-purple-900 rounded-lg p-3 text-xs text-gray-700 dark:text-purple-100 font-mono overflow-x-auto max-h-56 overflow-y-auto whitespace-pre-wrap leading-relaxed">
              {node.diagnostics}
            </pre>
          </div>
        )}

        {/* REQ-009: "not yet connected" banner — the one user flagged as unreadable.
            Light: faint slate panel + dark slate text. Dark: ColdVault purple-700/50
            with purple-200 text. Both pass readable contrast against their respective
            modal backgrounds. */}
        <p className="mb-4 text-sm text-gray-700 dark:text-purple-200">Based on: {boxBasis(node)}</p>

        {node.source === 'manifest' && !_hasLiveMetrics(node) && !node.metrics?._check_description && (
          <div className="mb-4 bg-gray-100 dark:bg-purple-700/50 border border-gray-200 dark:border-purple-600 rounded-lg p-3 text-sm text-gray-700 dark:text-purple-200">
            This node is defined in the infrastructure manifest but not yet connected to live monitoring.
            {node.metrics?.note && <div className="mt-1 text-gray-500 dark:text-purple-300">{node.metrics.note}</div>}
          </div>
        )}

        {/* Live metrics for manifest nodes WITH monitoring data */}
        {node.source === 'manifest' && _hasLiveMetrics(node) && (() => {
          const m = node.metrics || {}
          const checkDesc = m._check_description
          const lastPoll = m._last_poll
          const interval = m._poll_interval_s || 60
          const nowSec = Date.now() / 1000
          const ago = lastPoll ? Math.round(nowSec - lastPoll) : null
          const nextIn = ago !== null ? Math.max(0, interval - ago) : null
          const overdue = ago !== null && ago > interval
          const visibleMetrics = Object.entries(m).filter(([k]) => !k.startsWith('_') && k !== 'note' && k !== 'models')
          const models = Array.isArray(m.models) ? m.models : null
          void tick // trigger re-render on tick
          return (
            <div className="mb-4">
              <h3 className="text-xs font-semibold text-gray-500 dark:text-purple-300 uppercase tracking-wider mb-2">Live Monitoring</h3>
              {checkDesc && (
                <div className="mb-2 text-xs text-gray-600 dark:text-purple-200 bg-surface/30 dark:bg-purple-900/40 rounded px-2 py-1 font-mono">
                  {checkDesc}
                </div>
              )}
              {ago !== null && (
                <div className={`mb-2 text-xs ${overdue ? 'text-yellow-600 dark:text-yellow-400' : 'text-gray-500 dark:text-purple-300'}`}>
                  Checked {_formatAge(ago)} · {overdue ? 'refresh pending' : `Next in ${nextIn}s`}
                </div>
              )}
              {/* REQ-GHA-034: each model of this provider, as ColdVault reported its calls */}
              {models && (
                <div className="mb-2">
                  {models.length === 0 ? (
                    <div className="text-sm text-gray-500 dark:text-purple-300">No calls to these models in the last hour.</div>
                  ) : (
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="text-xs text-gray-500 dark:text-purple-300 text-left">
                          <th className="font-normal pb-1">Model (last hour)</th>
                          <th className="font-normal pb-1 text-right">Answered</th>
                          <th className="font-normal pb-1 text-right">Failed</th>
                        </tr>
                      </thead>
                      <tbody>
                        {models.map(md => {
                          const failed = (md.failed || 0) + (md.timed_out || 0)
                          return (
                            <tr key={md.id} className="align-top">
                              <td className="py-0.5 text-gray-800 dark:text-purple-100">
                                {md.name || md.id}
                                {failed > 0 && (
                                  <div className="text-xs text-gray-500 dark:text-purple-300">
                                    {[md.reason,
                                      md.recovered ? (md.backup ? `${md.backup} answered ${md.recovered - (md.unnamed || 0)}` : `${md.recovered} got a reply`) : null,
                                      md.backup && md.unnamed ? `${md.unnamed} got a reply` : null,
                                      md.unanswered ? `${md.unanswered} got no reply` : null,
                                      md.unknown ? `${md.unknown} with unknown outcome` : null].filter(Boolean).join(' · ')}
                                    {md.last_at ? ` · last ${clock(md.last_at)}` : ''}
                                  </div>
                                )}
                              </td>
                              <td className="py-0.5 text-right font-mono text-gray-800 dark:text-purple-100">{md.answered}</td>
                              <td className={`py-0.5 text-right font-mono ${failed > 0 ? 'text-red-600 dark:text-red-400' : 'text-gray-800 dark:text-purple-100'}`}>{failed}</td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  )}
                </div>
              )}
              <div className="grid grid-cols-2 gap-2">
                {visibleMetrics.map(([key, val]) => (
                  <div key={key} className="bg-surface/50 dark:bg-purple-900/50 rounded-lg p-2">
                    <div className="text-xs text-gray-500 dark:text-purple-300">{key.replace(/_/g, ' ')}</div>
                    <div className="text-sm text-gray-800 dark:text-purple-100 font-mono">{val !== null ? val : '—'}</div>
                  </div>
                ))}
              </div>
            </div>
          )
        })()}

        {/* AI Analysis — show for all nodes (manifest + discovered) */}
        {(
          <div className="mt-4">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <Brain size={14} className="text-accent-500 dark:text-accent-300" />
                <h3 className="text-xs font-semibold text-gray-500 dark:text-purple-300 uppercase tracking-wider">AI Analysis</h3>
                {analysisAge && (
                  <span className="flex items-center gap-1 text-xs text-gray-500 dark:text-purple-300">
                    <Clock size={10} />
                    {analysisAge}
                  </span>
                )}
              </div>
              {/* REQ-GHA-024: per-part overviews are written every 3 hours; no on-demand call */}
              <span className="text-xs text-gray-500 dark:text-purple-300">{overviewStamp(nodeAnalysis, now)}{readError ? ` · ${readError}` : ''}</span>
            </div>

            {/* REQ-GHA-024 clause 7: the last real overview stays; only a failed update is said */}
            {(nodeAnalysis?.error && nodeAnalysis?.analyzed_at) && (
              <div className="text-sm text-gray-600 dark:text-purple-200 bg-surface/50 dark:bg-purple-900/40 rounded px-2 py-1 mb-2">
                {`${nodeAnalysis.error} — showing the last overview.`}
              </div>
            )}

            {nodeAnalysis?.score != null ? (
              <div className="bg-surface dark:bg-purple-900/50 rounded-lg p-3 space-y-2">
                <div className="flex items-center gap-2">
                  <span className={`text-sm font-bold ${
                    nodeAnalysis.score >= 8 ? 'text-green-600 dark:text-green-400'
                    : nodeAnalysis.score >= 5 ? 'text-yellow-600 dark:text-yellow-400'
                    : 'text-red-600 dark:text-red-400'
                  }`}>{nodeAnalysis.score}/10</span>
                  <span className="text-sm text-gray-700 dark:text-purple-100">{nodeAnalysis.summary}</span>
                </div>
                {nodeAnalysis.issues?.length > 0 && (
                  <ul className="space-y-0.5">
                    {nodeAnalysis.issues.map((issue, i) => (
                      <li key={i} className="flex items-start gap-1.5 text-sm text-yellow-700 dark:text-yellow-300">
                        <AlertTriangle size={12} className="mt-0.5 flex-shrink-0" />
                        <span>{typeof issue === 'string' ? issue : issue?.description || JSON.stringify(issue)}</span>
                      </li>
                    ))}
                  </ul>
                )}
                {nodeAnalysis.issues?.length === 0 && (
                  <div className="flex items-center gap-1.5 text-sm text-green-600 dark:text-green-400">
                    <CheckCircle size={12} /><span>No issues detected</span>
                  </div>
                )}
                {nodeAnalysis.recommendations?.length > 0 && (
                  <ul className="space-y-0.5 pt-1 border-t border-border/70 dark:border-purple-700/50">
                    {nodeAnalysis.recommendations.map((rec, i) => (
                      <li key={i} className="text-sm text-gray-600 dark:text-purple-200">{typeof rec === 'string' ? rec : rec?.description || JSON.stringify(rec)}</li>
                    ))}
                  </ul>
                )}
              </div>
            ) : nodeAnalysis?.analyzed_at == null ? (
              <p className="text-sm text-gray-500 dark:text-purple-300">
                {nodeAnalysis?.error || 'No overview for this part yet.'}
              </p>
            ) : (
              <p className="text-sm text-gray-600 dark:text-purple-200">{nodeAnalysis?.summary || 'Analysis unavailable'}</p>
            )}
          </div>
        )}

        {/* REQ-GHA-020: Recheck via MCP — logged-in users only, never Live demo */}
        {canRecheck(node, isDemo) && (
          <div className="mt-4 bg-surface/30 dark:bg-purple-900/40 border border-border/50 dark:border-purple-700 rounded-lg p-3">
            <button
              onClick={handleRecheck}
              disabled={rechecking}
              className="w-full flex items-center justify-center gap-2 bg-surface hover:bg-surface/80 dark:bg-purple-900/40 dark:hover:bg-purple-900/60 border border-border dark:border-purple-700 rounded-lg py-2 text-sm text-gray-700 dark:text-purple-100 disabled:opacity-50"
            >
              <Cpu size={14} className={rechecking ? 'animate-pulse' : ''} />
              {rechecking ? 'Rechecking via MCP…' : 'Recheck via MCP'}
            </button>
            <label className="mt-2 flex items-start gap-2 text-xs text-gray-600 dark:text-purple-200">
              <input type="checkbox" checked={partner} onChange={e => setPartner(e.target.checked)} disabled={rechecking} />
              <span>Use Partner Mode. {PARTNER_NOTE}</span>
            </label>
            <div className="mt-1 text-xs text-gray-500 dark:text-purple-300">{WAKE_NOTE}</div>
            {recheck && (
              <div className={`mt-2 text-sm ${recheck.ok ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
                {recheck.text}
              </div>
            )}
          </div>
        )}

        {/* View Logs — REQ-GHA-032 clause 11 (amended 2026-11-09): only where GlassHood has a log
            source for the box; a box without one says so in one line, with the landscape's reason */}
        {noLogsReason(node) ? (
          <div className="mt-4 flex items-start gap-2 text-sm text-gray-500 dark:text-purple-300">
            <FileText size={14} className="mt-0.5 shrink-0" />
            <span>No logs GlassHood can read. {noLogsReason(node)}</span>
          </div>
        ) : (
          <button
            onClick={() => setShowLogs(true)}
            className="mt-4 w-full flex items-center justify-center gap-2 bg-surface hover:bg-surface/80 dark:bg-purple-900/40 dark:hover:bg-purple-900/60 border border-border dark:border-purple-700 rounded-lg py-2 text-sm text-gray-700 dark:text-purple-100 hover:text-gray-900 dark:hover:text-white transition-colors"
          >
            <FileText size={14} />
            View Logs
          </button>
        )}

        {/* Footer — only show if no live monitoring timer above */}
        {!(node.source === 'manifest' && _hasLiveMetrics(node)) && (
          <div className="mt-3 pt-3 border-t border-border dark:border-purple-700 text-sm text-gray-500 dark:text-purple-300">
            Last checked: {node.last_checked || '-'}
          </div>
        )}
      </div>

      {/* Full-screen log viewer */}
      {showLogs && (
        <LogViewerModal
          nodeId={node.id}
          nodeLabel={node.label}
          nodeStatus={node.status}
          isDemo={isDemo}
          onClose={() => setShowLogs(false)}
        />
      )}
    </div>
  )
}
