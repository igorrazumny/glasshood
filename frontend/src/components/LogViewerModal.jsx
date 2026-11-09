// File: frontend/src/components/LogViewerModal.jsx
// Purpose: Full-screen log viewer — fetches real logs (live) or sample data (demo)
// REQ-GHA-032: a quiet part shows its latest lines of the last 7 days (with the date)
// and every empty window says why. Amended 2026-11-09 (clauses 12 and 13): the window
// opens with several screens of lines, "Show earlier lines" adds what came before the
// oldest line shown, and nothing loaded is ever removed: newer lines join at the bottom,
// earlier lines at the top, and the reader keeps their place.

import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { X } from 'lucide-react'
import { usePolling } from '../hooks/usePolling'
import { apiFetch } from '../utils/api'
import { loadFailed } from '../utils/systems'
import { clock, dateTime } from '../utils/time'
import { EARLIER_EMPTY, PAGE, earlierRequest, mergeEntries } from '../utils/logsView'

const SKIPPED_NOTE = 'Too many lines share one moment; some of them are not shown.'

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
  const url = nodeId ? (isDemo ? `/api/demo/logs/${nodeId}` : `/api/logs/${nodeId}?lines=${PAGE}`) : null
  const logs = usePolling(url, 30000)
  const data = logs.data
  const [all, setAll] = useState([])            // every line loaded in this window, oldest first
  const [earlierNote, setEarlierNote] = useState(null)
  const [exhausted, setExhausted] = useState(false)
  const [loadingEarlier, setLoadingEarlier] = useState(false)
  const [wentBack, setWentBack] = useState(false)
  const allRef = useRef([])
  const bodyRef = useRef(null)
  const keepRef = useRef(null)                   // the body's height before earlier lines were added
  const firstRef = useRef(true)

  const loading = !data && !logs.error
  const error = data?.error || (logs.error ? loadFailed('The logs', logs.error) : null)
  const note = data?.note || null
  const provider = data?.window === 'provider'
  const week = wentBack || data?.window === '7d' || provider

  useEffect(() => {
    if (data?.entries) setAll(prev => mergeEntries(prev, data.entries))
  }, [data])
  useEffect(() => { allRef.current = all }, [all])

  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  // The reader's place: the bottom when the first lines arrive; kept when earlier lines are
  // added above; following newer lines only while the reader is already at the bottom.
  useLayoutEffect(() => {
    const el = bodyRef.current
    if (!el || !all.length) return
    if (keepRef.current != null) {
      el.scrollTop += el.scrollHeight - keepRef.current
      keepRef.current = null
    } else if (firstRef.current) {
      el.scrollTop = el.scrollHeight
      firstRef.current = false
    } else if (el.scrollHeight - el.scrollTop - el.clientHeight < 48) {
      el.scrollTop = el.scrollHeight
    }
  }, [all])

  const loadEarlier = async () => {
    const have = allRef.current
    if (!have.length || loadingEarlier) return
    setLoadingEarlier(true)
    setEarlierNote(null)
    try {
      const ask = earlierRequest(have)
      const body = await apiFetch(`/api/logs/${nodeId}?lines=${ask.lines}&before=${encodeURIComponent(ask.before)}`)
      const got = body?.entries || []
      if (body?.error) {
        setEarlierNote(body.error)
      } else if (mergeEntries(have, got).length === have.length) {
        setEarlierNote(ask.skipped ? `${SKIPPED_NOTE} ${EARLIER_EMPTY}` : (body?.note || EARLIER_EMPTY))
        setExhausted(true)
      } else {
        keepRef.current = bodyRef.current?.scrollHeight ?? null
        setWentBack(true)
        setAll(prev => mergeEntries(prev, got))
        if (ask.skipped) setEarlierNote(SKIPPED_NOTE)
      }
    } catch (e) {
      setEarlierNote(loadFailed('Earlier lines', e?.message || e))
    } finally {
      setLoadingEarlier(false)
    }
  }

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
        <div ref={bodyRef} className="flex-1 bg-card dark:bg-purple-800 border border-border dark:border-purple-700 rounded-lg overflow-y-auto font-mono text-xs p-4 min-h-0">
          {/* clause 13: what came before the oldest line shown, as often as wanted */}
          {!isDemo && all.length > 0 && (
            <div className="mb-3 flex items-center gap-3">
              {!exhausted && (
                <button type="button" onClick={loadEarlier} disabled={loadingEarlier}
                        className="px-2 py-1 rounded border border-border dark:border-purple-600 text-gray-700 dark:text-purple-100 hover:bg-surface dark:hover:bg-purple-700/40 disabled:opacity-50">
                  {loadingEarlier ? 'Loading earlier lines…' : 'Show earlier lines'}
                </button>
              )}
              {earlierNote && <span className="text-gray-500 dark:text-purple-300">{earlierNote}</span>}
            </div>
          )}
          {loading && (
            <div className="text-gray-500 animate-pulse">Loading logs...</div>
          )}
          {error && (
            <div className="text-yellow-500 mb-3">{error}</div>
          )}
          {note && (
            <div className="text-gray-500 dark:text-purple-300 mb-3">{note}</div>
          )}
          {!loading && all.length === 0 && !error && !note && (
            <div className="text-gray-600">No log entries found in the last hour.</div>
          )}
          {all.map((entry, i) => {
            const sevColor = SEVERITY_COLORS[entry.severity] || SEVERITY_COLORS.DEFAULT
            return (
              <div key={`${entry.timestamp}|${i}`} className="flex gap-3 py-0.5 hover:bg-surface/50 dark:hover:bg-purple-700/30 leading-relaxed">
                <span className="text-gray-600 whitespace-nowrap shrink-0">
                  {(week ? dateTime(entry.timestamp) : clock(entry.timestamp, { seconds: true })) || '--:--:--'}
                </span>
                <span className={`${sevColor} w-16 shrink-0`}>{entry.severity}</span>
                <span className="text-gray-300 whitespace-pre-wrap break-all">{entry.message}</span>
              </div>
            )
          })}
        </div>

        {/* Footer */}
        <div className="mt-2 text-xs text-gray-600 flex justify-between">
          <span>{all.length} lines ({provider ? 'published by the provider' : week ? 'last 7 days' : 'last 1 hour'})</span>
          <span>{isDemo ? 'Sample data' : provider ? "Provider's public status page" : 'Cloud logs'}</span>
        </div>
      </div>
    </div>
  )
}
