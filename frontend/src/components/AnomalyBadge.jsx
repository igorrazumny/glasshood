// File: frontend/src/components/AnomalyBadge.jsx
// Purpose: Anomaly indicator badge for topology sidebar — shows active anomalies with z-scores

import { useState } from 'react'

const SEVERITY_COLORS = {
  critical: { bg: 'bg-red-900/40', border: 'border-red-700/50', text: 'text-red-400', dot: 'bg-red-500' },
  warning: { bg: 'bg-yellow-900/40', border: 'border-yellow-700/50', text: 'text-yellow-400', dot: 'bg-yellow-500' },
}

function ConfidenceBar({ confidence }) {
  const pct = Math.round(confidence * 100)
  const color = pct > 80 ? 'bg-red-500' : pct > 60 ? 'bg-yellow-500' : 'bg-blue-500'
  return (
    <div className="flex items-center gap-1.5">
      <div className="w-12 h-1 bg-gray-700 rounded-full overflow-hidden">
        <div className={`h-full ${color} rounded-full`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-gray-500">{pct}%</span>
    </div>
  )
}

export default function AnomalyBadge({ anomalies = [], onSelect }) {
  const [expanded, setExpanded] = useState(false)

  if (!anomalies || anomalies.length === 0) return null

  const criticalCount = anomalies.filter(a => a.severity === 'critical').length

  return (
    <div className="mb-3">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-3 py-2 rounded-lg bg-surface-elevated border border-gray-700/50 hover:border-gray-600/50 transition-colors"
      >
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${criticalCount > 0 ? 'bg-red-500 animate-pulse' : 'bg-yellow-500'}`} />
          <span className="text-sm font-medium text-gray-300">
            Anomalies
          </span>
          <span className="text-sm text-gray-500">
            ({anomalies.length})
          </span>
        </div>
        <span className="text-xs text-gray-500">{expanded ? '\u25B2' : '\u25BC'}</span>
      </button>

      {expanded && (
        <div className="mt-1 space-y-1">
          {anomalies.map((a, i) => {
            const style = SEVERITY_COLORS[a.severity] || SEVERITY_COLORS.warning
            return (
              <div key={`${a.metric}-${a.timestamp || i}`} onClick={() => onSelect?.(a)}
                className={`px-3 py-2 rounded-lg ${style.bg} border ${style.border} ${onSelect ? 'cursor-pointer hover:brightness-125' : ''}`}>
                <div className="flex items-center justify-between">
                  <span className={`text-sm font-medium ${style.text}`}>{a.metric}</span>
                  <span className="text-sm text-gray-500">z={a.z_score}</span>
                </div>
                <div className="flex items-center justify-between mt-1">
                  <span className="text-sm text-gray-400">
                    {a.value} (baseline: {a.baseline_mean})
                  </span>
                  <ConfidenceBar confidence={a.confidence || 0} />
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
