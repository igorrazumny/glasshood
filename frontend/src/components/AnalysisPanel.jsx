// File: frontend/src/components/AnalysisPanel.jsx
// Purpose: AI analysis panel — score, summary, issues, recommendations
// REQ-009: theme-aware classes throughout — light + dark: pairs for every
// surface so the panel reads correctly in both themes.

import { useState } from 'react'
import { Brain, ChevronDown, ChevronRight, RefreshCw, AlertTriangle, CheckCircle, Server, Shield, Loader2 } from 'lucide-react'
import { apiFetch } from '../utils/api'
import { statsSummary } from '../utils/canvasParts.js'
import { overviewStamp, spendLine } from '../utils/overview.js'
import AiOfflineLine from './AiOfflineLine'
import { assessmentLine, attentionItems, loadFailed } from '../utils/systems.js'

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

function TopologyStats({ topology, canvas }) {
  // REQ-GHA-023 clause 5: count what the canvas draws (statsNodes waits for the topology).
  const summary = statsSummary(topology, canvas)
  if (!summary) return null
  const { total, byStatus, overall } = summary
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
      {overall && (
        <div className="mt-1.5 text-sm text-gray-500 dark:text-purple-300">
          Overall: <span className={statusColor[overall] || 'text-gray-700 dark:text-purple-100'}>{overall}</span>
        </div>
      )}
    </div>
  )
}

// REQ-GHA-037 clauses 7 and 9: the title names what the overview covers; on the home view or
// a group it lists each system's own short assessment; box counts only for one system
function SystemsList({ onOpenAlert, cards, descriptions, loadError, systemsError }) {
  if (!cards.length && systemsError) {
    return <p className="text-sm text-yellow-700 dark:text-yellow-300">{loadFailed('Your systems', systemsError)}</p>
  }
  if (!cards.length) {
    return (
      <p className="text-gray-500 dark:text-purple-300 text-sm flex items-center gap-2">
        <Loader2 size={14} className="animate-spin" /> Loading your systems…
      </p>
    )
  }
  const off = cards.find(c => c.offline)
  if (off) return <AiOfflineLine offline={off.offline} onOpenAlert={onOpenAlert} />
  const items = attentionItems(cards, descriptions)
  if (!items.length) {
    return (
      <div className="flex items-center gap-2 text-green-700 dark:text-green-400 text-sm">
        <CheckCircle size={12} /><span>Nothing needs attention</span>
      </div>
    )
  }
  return (
    <div>
      <h3 className="text-xs font-semibold text-gray-500 dark:text-purple-300 mb-1">Needs attention</h3>
      {loadError && <p className="text-xs text-yellow-700 dark:text-yellow-300">{loadFailed('A newer assessment', loadError)}</p>}
      <ul className="space-y-3">
        {items.map(a => (
          <li key={a.id}>
            <div className="text-sm font-semibold text-gray-800 dark:text-purple-100">
              {a.label} <span className="font-normal text-xs text-gray-500 dark:text-purple-300">{a.word}{a.reason ? ` · ${a.reason}` : ''}</span>
            </div>
            {a.issues.length > 0 && <ul className="list-disc ml-4 text-sm text-gray-600 dark:text-purple-200">{a.issues.map(i => <li key={String(i)}>{String(i)}</li>)}</ul>}
          </li>
        ))}
      </ul>
    </div>
  )
}

export default function AnalysisPanel({ data, topology, canvas, scopeLabel = 'All monitored systems', listCards = null,
                                        descriptions = null, showStats = true, loading = false, onOpenAlert = null,
                                        fetchError = null, descriptionsError = null, systemsError = null }) {
  const [refreshing, setRefreshing] = useState(false)
  const [refreshNote, setRefreshNote] = useState('')
  const [open, setOpen] = useState(true)   // REQ-GHA-045 clause 7: the reader can fold it away

  const handleRefresh = async () => {
    setRefreshing(true)
    setRefreshNote('')
    try {
      await apiFetch('/api/analysis/refresh', { method: 'POST' })
    } catch (e) {
      setRefreshNote(e?.message || 'A fresh overview is not possible right now')
    } finally {
      setRefreshing(false)
    }
  }

  const analysis = data || {}
  const hasData = !!analysis.summary
  // REQ-GHA-024: a system's own job says what is happening now
  const life = analysis.job ? assessmentLine(analysis, Date.now()) : null
  // REQ-GHA-024: only an operator gets spend and the refresh control; a viewer only reads.
  const spend = analysis.spend

  return (
    <div className="mb-2 bg-card dark:bg-purple-800 border border-border dark:border-purple-700 rounded-lg p-4 flex flex-col gap-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className="flex items-center gap-2 text-left">
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          <Brain size={16} className="text-accent-500 dark:text-accent-300" />
          <span className="text-base font-semibold text-gray-900 dark:text-white">AI overview · {scopeLabel}</span>
        </button>
        {spend && (
          <button
            onClick={handleRefresh}
            disabled={refreshing || analysis.refresh_in_s > 0}
            className="text-gray-500 hover:text-gray-800 dark:text-purple-300 dark:hover:text-white transition-colors disabled:opacity-30"
            title={analysis.refresh_in_s > 0 ? `Fresh overview possible in ${Math.ceil(analysis.refresh_in_s / 60)} min` : 'Run a fresh AI evaluation now'}
          >
            <RefreshCw size={12} className={refreshing ? 'animate-spin' : ''} />
          </button>
        )}
      </div>

      <div className={`${open ? 'flex' : 'hidden'} flex-col gap-3`}>
      {/* REQ-GHA-024 clause 1: when it was written, right on top (the model is not named) */}
      {!listCards && !analysis.ai_offline && <p className="text-xs text-gray-500 dark:text-purple-300 -mt-2">{overviewStamp(analysis)}</p>}
      {!listCards && !analysis.ai_offline && analysis.error && (
        <p className="text-xs text-yellow-700 dark:text-yellow-300">{analysis.error}{hasData ? ' — showing the last overview.' : ''}</p>
      )}
      {!listCards && life?.job && <p className="text-xs text-gray-500 dark:text-purple-300">{life.job}</p>}
      {!listCards && fetchError && (
        <p className="text-xs text-yellow-700 dark:text-yellow-300">
          {hasData ? `${loadFailed('A newer overview', fetchError)} Showing the last one.` : loadFailed('The AI overview', fetchError)}
        </p>
      )}
      {refreshNote && <p className="text-xs text-gray-500 dark:text-purple-300">{refreshNote}</p>}

      {listCards ? (
        <SystemsList onOpenAlert={onOpenAlert} cards={listCards} descriptions={descriptions} loadError={descriptionsError} systemsError={systemsError} />
      ) : analysis.ai_offline ? (
        <div className="flex flex-col gap-2">
          <AiOfflineLine offline={analysis.ai_offline} onOpenAlert={onOpenAlert} />
          {hasData
            ? <details><summary className="text-xs font-semibold text-gray-500 dark:text-purple-300 cursor-pointer">Last evaluation, {overviewStamp(analysis).replace(/^Evaluated /, '')}</summary>
                <p className="text-sm text-gray-700 dark:text-purple-100 leading-relaxed mt-1">{analysis.summary}</p>
                {analysis.issues?.length > 0 && <ul className="list-disc ml-4 mt-1 text-sm text-gray-700 dark:text-purple-100">{analysis.issues.map(i => <li key={i}>{i}</li>)}</ul>}
                {analysis.recommendations?.length > 0 && <ul className="list-disc ml-4 mt-1 text-sm text-gray-700 dark:text-purple-100">{analysis.recommendations.map(r => <li key={r}>{r}</li>)}</ul>}
              </details>
            : <p className="text-sm text-gray-500 dark:text-purple-300">Not evaluated yet.</p>}
        </div>
      ) : !hasData ? (
        fetchError ? null : <p className="text-gray-500 dark:text-purple-300 text-sm flex items-center gap-2">
          {(life ? life.busy : !analysis.error) && <Loader2 size={14} className="animate-spin" />}
          {life ? life.text : analysis.error ? 'No overview yet.' : (loading || !data ? 'Loading the AI overview…' : 'AI evaluation in progress…')}
        </p>
      ) : (
        <>
          {/* Summary first: how the system is doing, in plain words */}
          <div className="flex items-start gap-3">
            <ScoreBadge score={analysis.score} />
            <p className="text-gray-700 dark:text-purple-100 text-sm leading-relaxed">{analysis.summary}</p>
          </div>

          {analysis.issues?.length > 0 && (
            <div>
              <h3 className="text-xs font-semibold text-gray-500 dark:text-purple-300 uppercase mb-1">Needs attention</h3>
              <ul className="space-y-1">
                {analysis.issues.map((issue, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-yellow-700 dark:text-yellow-300">
                    <AlertTriangle size={12} className="mt-0.5 flex-shrink-0" />
                    <span>{String(issue)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {analysis.issues?.length === 0 && (
            <div className="flex items-center gap-2 text-green-700 dark:text-green-400 text-sm">
              <CheckCircle size={12} />
              <span>Nothing needs attention</span>
            </div>
          )}

          {analysis.recommendations?.length > 0 && (
            <div>
              <h3 className="text-xs font-semibold text-gray-500 dark:text-purple-300 uppercase mb-1">Next steps</h3>
              <ul className="space-y-1">
                {analysis.recommendations.map((rec, i) => (
                  <li key={i} className="text-sm text-gray-600 dark:text-purple-200">{String(rec)}</li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}

      {spend && (
        <p className="text-xs text-gray-500 dark:text-purple-300">
          {spendLine(spend)}
        </p>
      )}

      {showStats && <TopologyStats topology={topology} canvas={canvas} />}
      </div>
    </div>
  )
}
