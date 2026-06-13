// File: frontend/src/components/VerificationReportModal.jsx
// Purpose: REQ-603 — Verification report modal. Shows probe results per node.
// User reviews and decides whether to proceed. Informational, not a gate.

import { useState } from 'react'
import { X, CheckCircle, XCircle, AlertTriangle, HelpCircle, Loader2 } from 'lucide-react'

const STATUS_CONFIG = {
  verified:        { icon: CheckCircle, color: 'text-green-400', bg: 'bg-green-500/10', label: 'Verified' },
  failed:          { icon: XCircle,     color: 'text-red-400',   bg: 'bg-red-500/10',   label: 'Failed' },
  declared:        { icon: HelpCircle,  color: 'text-gray-400',  bg: 'bg-gray-500/10',  label: 'Declared' },
  confirmed_exists:{ icon: CheckCircle, color: 'text-gray-400',  bg: 'bg-gray-500/10',  label: 'Exists (offline)' },
  unverified:      { icon: AlertTriangle, color: 'text-yellow-400', bg: 'bg-yellow-500/10', label: 'Unverified' },
  skipped:         { icon: HelpCircle,  color: 'text-gray-500',  bg: 'bg-gray-500/10',  label: 'Skipped' },
}

function StatusBadge({ status }) {
  const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.skipped
  const Icon = cfg.icon
  return (
    <span className={`inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded ${cfg.bg} ${cfg.color}`}>
      <Icon size={12} />
      {cfg.label}
    </span>
  )
}

function SummaryBar({ summary }) {
  if (!summary) return null
  const total = (summary.verified || 0) + (summary.failed || 0) + (summary.declared || 0) + (summary.unverified || 0)
  if (total === 0) return null
  return (
    <div className="flex items-center gap-3 text-xs mb-3">
      {summary.verified > 0 && <span className="text-green-400">{summary.verified} verified</span>}
      {summary.failed > 0 && <span className="text-red-400">{summary.failed} failed</span>}
      {summary.declared > 0 && <span className="text-gray-400">{summary.declared} declared</span>}
      {summary.unverified > 0 && <span className="text-yellow-400">{summary.unverified} unverified</span>}
      <span className="text-gray-500 ml-auto">{total} nodes</span>
    </div>
  )
}

function NodeRow({ node }) {
  const [expanded, setExpanded] = useState(false)
  const hasErrors = node.errors && node.errors.length > 0
  return (
    <div className="border border-border dark:border-purple-700 rounded-lg mb-2">
      <div className="flex items-center justify-between px-3 py-2 cursor-pointer hover:bg-white/5"
        onClick={() => hasErrors && setExpanded(!expanded)}>
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-gray-200">{node.node_id}</span>
          <span className="text-xs text-gray-500">{node.tier}</span>
        </div>
        <StatusBadge status={node.status} />
      </div>
      {expanded && hasErrors && (
        <div className="px-3 pb-2 space-y-1">
          {node.errors.map((err, i) => (
            <div key={i} className="text-xs text-red-400/80 pl-2 border-l-2 border-red-500/30">{err}</div>
          ))}
          {node.probe_result && (
            <div className="text-xs text-gray-500 mt-1">
              {node.probe_result.latency_ms && `Latency: ${node.probe_result.latency_ms}ms`}
              {node.probe_result.status_code && ` | HTTP ${node.probe_result.status_code}`}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function VerificationReportModal({ reports, loading, onAccept, onRecheck, onClose }) {
  if (!reports && !loading) return null

  const hasFailures = reports?.some(r => r.summary?.failed > 0)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={onClose}>
      <div className="absolute inset-0 bg-black/60" />
      <div className="relative bg-card dark:bg-purple-800 border border-border dark:border-purple-700 rounded-xl p-5 max-w-2xl w-full mx-4 max-h-[85vh] overflow-y-auto"
        onClick={e => e.stopPropagation()}>

        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-100">Verification Report</h2>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-300"><X size={18} /></button>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-12 text-gray-400">
            <Loader2 size={24} className="animate-spin mr-2" />
            Verifying endpoints...
          </div>
        ) : (
          <>
            {/* Per-solution reports */}
            {reports?.map((report, idx) => (
              <div key={idx} className="mb-6">
                <div className="flex items-center gap-2 mb-2">
                  <h3 className="text-sm font-semibold text-gray-300">
                    {report.solution || report.product}
                  </h3>
                  <span className="text-xs text-gray-500">{report.environment}</span>
                </div>
                <SummaryBar summary={report.summary} />
                {report.nodes?.map((node, ni) => (
                  <NodeRow key={ni} node={node} />
                ))}
              </div>
            ))}

            {/* No reports */}
            {(!reports || reports.length === 0) && (
              <p className="text-gray-500 text-sm py-4">No verification data available.</p>
            )}

            {/* Actions */}
            <div className="flex items-center justify-between mt-4 pt-4 border-t border-border dark:border-purple-700">
              <button onClick={onRecheck}
                className="text-sm text-gray-400 hover:text-gray-200 flex items-center gap-1">
                <Loader2 size={14} /> Re-check
              </button>
              <div className="flex gap-2">
                <button onClick={onClose}
                  className="px-4 py-2 text-sm text-gray-400 hover:text-gray-200 border border-border dark:border-purple-700 rounded-lg">
                  Cancel
                </button>
                <button onClick={onAccept}
                  className={`px-4 py-2 text-sm font-medium rounded-lg ${
                    hasFailures
                      ? 'bg-yellow-600 hover:bg-yellow-500 text-white'
                      : 'bg-green-600 hover:bg-green-500 text-white'
                  }`}>
                  {hasFailures ? 'Accept with issues' : 'Accept & Continue'}
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
