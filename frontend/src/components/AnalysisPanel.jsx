// File: frontend/src/components/AnalysisPanel.jsx
// Purpose: AI analysis panel — score, summary, issues, recommendations
// REQ-009: theme-aware classes throughout — light + dark: pairs for every
// surface so the panel reads correctly in both themes.

import { useState } from 'react'
import { Brain, RefreshCw, AlertTriangle, CheckCircle, Server, Shield } from 'lucide-react'
import { apiFetch } from '../utils/api'

function ScoreBadge({ score }) {
  if (score === null || score === undefined) return null
  const color =
    score >= 8 ? 'text-green-700 dark:text-green-400 border-green-300 dark:border-green-400/30'
    : score >= 5 ? 'text-yellow-700 dark:text-yellow-400 border-yellow-300 dark:border-yellow-400/30'
    : 'text-red-700 dark:text-red-400 border-red-300 dark:border-red-400/30'
  return (
    <span className={`text-2xl font-bold ${color} border rounded-lg px-3 py-1`}>
      {score}/10
    </span>
  )
}

function TopologyStats({ topology }) {
  if (!topology?.nodes?.length) return null

  const nodes = topology.nodes
  const total = nodes.length
  const byStatus = {}
  for (const n of nodes) {
    const s = n.status || 'unknown'
    byStatus[s] = (byStatus[s] || 0) + 1
  }
  // REQ-009: status color pairs — light uses semantic-700, dark uses -400.
  const statusColor = {
    healthy: 'text-green-700 dark:text-green-400', deployed: 'text-green-700 dark:text-green-400',
    degraded: 'text-yellow-700 dark:text-yellow-400', error: 'text-red-700 dark:text-red-400',
    disconnected: 'text-gray-500 dark:text-purple-300', unknown: 'text-gray-500 dark:text-purple-300',
  }

  return (
    <div className="mb-3 pb-3 border-b border-border dark:border-purple-700">
      <div className="flex items-center gap-2 mb-2">
        <Server size={14} className="text-blue-600 dark:text-blue-400" />
        <span className="text-xs font-semibold text-gray-500 dark:text-purple-300 uppercase tracking-wider">System Overview</span>
      </div>
      <div className="flex items-center gap-1 mb-1.5">
        <Shield size={12} className="text-cyan-600 dark:text-cyan-400" />
        <span className="text-sm text-gray-600 dark:text-purple-200">{total} nodes monitored</span>
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-0.5">
        {Object.entries(byStatus).sort().map(([status, count]) => (
          <span key={status} className={`text-sm ${statusColor[status] || 'text-gray-500 dark:text-purple-300'}`}>
            {count} {status}
          </span>
        ))}
      </div>
      {topology.overall_status && (
        <div className="mt-1.5 text-sm text-gray-500 dark:text-purple-300">
          Overall: <span className={statusColor[topology.overall_status] || 'text-gray-700 dark:text-purple-100'}>{topology.overall_status}</span>
        </div>
      )}
    </div>
  )
}

export default function AnalysisPanel({ data, topology }) {
  const [refreshing, setRefreshing] = useState(false)

  const handleRefresh = async () => {
    setRefreshing(true)
    try {
      await apiFetch('/api/analysis/refresh', { method: 'POST' })
    } catch (e) {
      // Rate limited or error — ignore, cached data stays
    } finally {
      setRefreshing(false)
    }
  }

  const analysis = data || {}
  const hasData = analysis.score !== null && analysis.score !== undefined

  return (
    <div className="h-full bg-card dark:bg-purple-800 border border-border dark:border-purple-700 rounded-lg p-4 flex flex-col gap-3 overflow-y-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Brain size={16} className="text-accent-500 dark:text-accent-300" />
          <span className="text-base font-semibold text-gray-900 dark:text-white">AI Analysis</span>
          {analysis.stale && (
            <span className="text-xs bg-yellow-100 dark:bg-yellow-400/10 text-yellow-700 dark:text-yellow-400 px-1.5 py-0.5 rounded">stale</span>
          )}
        </div>
        <button
          onClick={handleRefresh}
          disabled={refreshing}
          className="text-gray-500 hover:text-gray-800 dark:text-purple-300 dark:hover:text-white transition-colors"
          title="Refresh analysis"
        >
          <RefreshCw size={12} className={refreshing ? 'animate-spin' : ''} />
        </button>
      </div>

      <TopologyStats topology={topology} />

      {!hasData ? (
        <p className="text-gray-500 dark:text-purple-300 text-sm">Waiting for first analysis...</p>
      ) : (
        <>
          {/* Score */}
          <div className="flex justify-center py-2">
            <ScoreBadge score={analysis.score} />
          </div>

          {/* Summary */}
          <p className="text-gray-700 dark:text-purple-100 text-sm leading-relaxed">{analysis.summary}</p>

          {/* Issues */}
          {analysis.issues?.length > 0 && (
            <div>
              <h3 className="text-xs font-semibold text-gray-500 dark:text-purple-300 uppercase mb-1">Issues</h3>
              <ul className="space-y-1">
                {analysis.issues.map((issue, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-yellow-700 dark:text-yellow-300">
                    <AlertTriangle size={12} className="mt-0.5 flex-shrink-0" />
                    <span>{typeof issue === 'string' ? issue : issue?.description || JSON.stringify(issue)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {analysis.issues?.length === 0 && (
            <div className="flex items-center gap-2 text-green-700 dark:text-green-400 text-sm">
              <CheckCircle size={12} />
              <span>No issues detected</span>
            </div>
          )}

          {/* Recommendations */}
          {analysis.recommendations?.length > 0 && (
            <div>
              <h3 className="text-xs font-semibold text-gray-500 dark:text-purple-300 uppercase mb-1">Recommendations</h3>
              <ul className="space-y-1">
                {analysis.recommendations.map((rec, i) => (
                  <li key={i} className="text-sm text-gray-600 dark:text-purple-200">{typeof rec === 'string' ? rec : rec?.description || JSON.stringify(rec)}</li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}

      <div className="mt-auto text-xs pt-2 border-t border-border dark:border-purple-700">
        <a
          href="https://9robots.ai"
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1.5 text-gray-500 hover:text-gray-700 dark:text-purple-300 dark:hover:text-purple-100 transition-colors"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" className="opacity-40 group-hover:opacity-70">
            <rect x="3" y="3" width="18" height="18" rx="4" stroke="currentColor" strokeWidth="2"/>
            <path d="M8 12h8M12 8v8" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
          </svg>
          Powered by 9robots.ai
        </a>
      </div>
    </div>
  )
}
