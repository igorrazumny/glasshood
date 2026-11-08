// File: frontend/src/components/LogViewerModal.jsx
// Purpose: Full-screen log viewer — fetches real GCP logs (live) or sample data (demo)
// REQ-GHA-032: a quiet part shows its latest lines of the last 7 days (with the date)
// and every empty window says why.

import { useEffect, useRef } from 'react'
import { X } from 'lucide-react'
import { usePolling } from '../hooks/usePolling'
import { loadFailed } from '../utils/systems'
import { clock, dateTime } from '../utils/time'

const SEVERITY_COLORS = {
  ERROR: 'text-red-400',
  WARNING: 'text-yellow-400',
  INFO: 'text-blue-400',
  DEBUG: 'text-gray-500',
  DEFAULT: 'text-gray-400',
}

// REQ-704: logConfig prop removed (filter/project are derived server-side
// from node_id via the compiled manifest). Callers no longer pass it.
export default function LogViewerModal({ nodeId, nodeLabel, nodeStatus, isDemo, onClose }) {
  // Logs already opened show at once from this session's store and are read again in the
  // background every 30 s, so newer lines appear without waiting (same store as the views:
  // one session's logs never show in the next session)
  const url = nodeId ? (isDemo ? `/api/demo/logs/${nodeId}` : `/api/logs/${nodeId}`) : null
  const logs = usePolling(url, 30000)
  const data = logs.data
  const entries = data?.entries || []
  const loading = !data && !logs.error
  const error = data?.error || (logs.error ? loadFailed('The logs', logs.error) : null)
  const note = data?.note || null
  const week = data?.window === '7d' || data?.window === 'provider'
  const provider = data?.window === 'provider'
  const bottomRef = useRef(null)

  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  useEffect(() => {
    if (!loading && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [loading, entries.length])   // only when lines arrive, so a refresh does not move the reader

  if (!nodeId) return null

  return (
    <div className="fixed inset-0 z-[60] flex flex-col bg-surface/95 dark:bg-purple-950/95" onClick={onClose}>
      <div className="flex-1 flex flex-col max-w-6xl w-full mx-auto p-4" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-semibold text-white">Logs: {nodeLabel}</h2>
            <span className="text-xs text-gray-500">{nodeId}</span>
            {logs.lastUpdated && (
              <span className="text-xs text-gray-500 dark:text-purple-300">read {clock(logs.lastUpdated)} · updates every 30 s</span>
            )}
            {nodeStatus && (
              <span className={`text-xs px-2 py-0.5 rounded font-medium ${
                nodeStatus === 'healthy' || nodeStatus === 'deployed' ? 'bg-green-500/10 text-green-400' :
                nodeStatus === 'error' ? 'bg-red-500/10 text-red-400' :
                nodeStatus === 'degraded' ? 'bg-yellow-500/10 text-yellow-400' :
                'bg-gray-500/10 text-gray-400'
              }`}>{nodeStatus}</span>
            )}
          </div>
          <button onClick={onClose} className="text-gray-500 hover:text-white transition-colors">
            <X size={20} />
          </button>
        </div>

        {/* Log body */}
        <div className="flex-1 bg-card dark:bg-purple-800 border border-border dark:border-purple-700 rounded-lg overflow-y-auto font-mono text-xs p-4 min-h-0">
          {loading && (
            <div className="text-gray-500 animate-pulse">Loading logs...</div>
          )}
          {error && (
            <div className="text-yellow-500 mb-3">{error}</div>
          )}
          {note && (
            <div className="text-gray-500 dark:text-purple-300 mb-3">{note}</div>
          )}
          {!loading && entries.length === 0 && !error && !note && (
            <div className="text-gray-600">No log entries found in the last hour.</div>
          )}
          {entries.map((entry, i) => {
            const sevColor = SEVERITY_COLORS[entry.severity] || SEVERITY_COLORS.DEFAULT
            return (
              <div key={i} className="flex gap-3 py-0.5 hover:bg-surface/50 dark:hover:bg-purple-700/30 leading-relaxed">
                <span className="text-gray-600 whitespace-nowrap shrink-0">
                  {(week ? dateTime(entry.timestamp) : clock(entry.timestamp, { seconds: true })) || '--:--:--'}
                </span>
                <span className={`${sevColor} w-16 shrink-0`}>{entry.severity}</span>
                <span className="text-gray-300 whitespace-pre-wrap break-all">{entry.message}</span>
              </div>
            )
          })}
          <div ref={bottomRef} />
        </div>

        {/* Footer */}
        <div className="mt-2 text-xs text-gray-600 flex justify-between">
          <span>{entries.length} entries ({provider ? 'published by the provider' : week ? 'last 7 days' : 'last 1 hour'})</span>
          <span>{isDemo ? 'Sample data' : provider ? "Provider's public status page" : 'Cloud logs'}</span>
        </div>
      </div>
    </div>
  )
}
