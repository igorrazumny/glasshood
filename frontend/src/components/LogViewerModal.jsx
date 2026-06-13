// File: frontend/src/components/LogViewerModal.jsx
// Purpose: Full-screen log viewer — fetches real GCP logs (live) or sample data (demo)

import { useState, useEffect, useRef } from 'react'
import { X } from 'lucide-react'
import { apiFetch } from '../utils/api'

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
  const [entries, setEntries] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const bottomRef = useRef(null)

  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  useEffect(() => {
    if (!nodeId) return
    setLoading(true)
    setError(null)

    // REQ-704: filter+project are derived server-side from node_id via the
    // compiled manifest. We no longer send log_filter / log_project query
    // params from the client (accepted-and-ignored on the backend, but still
    // sending them invites accidental reliance and gives a misleading sense
    // of where the trust boundary is).
    const url = isDemo ? `/api/demo/logs/${nodeId}` : `/api/logs/${nodeId}`
    const fetcher = isDemo ? fetch(url).then(r => r.json()) : apiFetch(url)

    fetcher
      .then(data => {
        setEntries(data.entries || [])
        if (data.error) setError(data.error)
      })
      .catch(err => setError(err.message))
      .finally(() => setLoading(false))
  }, [nodeId, isDemo])

  useEffect(() => {
    if (!loading && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [loading, entries])

  if (!nodeId) return null

  return (
    <div className="fixed inset-0 z-[60] flex flex-col bg-surface/95 dark:bg-purple-950/95" onClick={onClose}>
      <div className="flex-1 flex flex-col max-w-6xl w-full mx-auto p-4" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-semibold text-white">Logs: {nodeLabel}</h2>
            <span className="text-xs text-gray-500">{nodeId}</span>
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
            <div className="text-yellow-500 mb-3">Note: {error}</div>
          )}
          {!loading && entries.length === 0 && !error && (
            <div className="text-gray-600">No log entries found in the last hour.</div>
          )}
          {entries.map((entry, i) => {
            const sevColor = SEVERITY_COLORS[entry.severity] || SEVERITY_COLORS.DEFAULT
            return (
              <div key={i} className="flex gap-3 py-0.5 hover:bg-surface/50 dark:hover:bg-purple-700/30 leading-relaxed">
                <span className="text-gray-600 whitespace-nowrap shrink-0">
                  {entry.timestamp ? new Date(entry.timestamp).toLocaleTimeString() : '--:--:--'}
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
          <span>{entries.length} entries (last 1 hour)</span>
          <span>{isDemo ? 'Sample data' : 'GCP Cloud Logging'}</span>
        </div>
      </div>
    </div>
  )
}
