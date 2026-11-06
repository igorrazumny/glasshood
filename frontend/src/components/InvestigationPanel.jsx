// File: frontend/src/components/InvestigationPanel.jsx
// Purpose: REQ-GHA-029 clauses 3-5 — "Investigate deeper" for one alarm, its report (executive
// summary first) and follow-ups. Signed-in operators start and follow up; everyone can read a
// saved report. The report text is shown as plain text only.

import { useEffect, useState } from 'react'
import { Search, RefreshCw, ExternalLink } from 'lucide-react'
import { apiFetch } from '../utils/api'
import { alarmRef, patternLabel, errorText } from '../utils/alarms'

const BOX = 'rounded-lg p-3 bg-surface dark:bg-purple-900/50 border border-border dark:border-purple-700'
const HEAD = 'text-xs font-semibold text-gray-500 dark:text-purple-300 uppercase'
const TEXT = 'text-sm text-gray-700 dark:text-purple-100 mt-1 leading-relaxed'
const BUTTON = 'w-full py-2 rounded-lg border border-blue-600 dark:border-blue-400 text-blue-700 dark:text-blue-300 hover:bg-blue-50 dark:hover:bg-blue-500/10 disabled:opacity-50 text-sm font-medium transition-colors flex items-center justify-center gap-2'

const hhmm = iso => (iso ? new Date(iso).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' }) : '')

function Section({ title, children }) {
  return (
    <div className={BOX}>
      <span className={HEAD}>{title}</span>
      {children}
    </div>
  )
}

function Report({ report }) {
  return (
    <div className="space-y-3">
      <div className="rounded-lg p-3 bg-blue-50 dark:bg-blue-500/10 border border-blue-300 dark:border-blue-500/30">
        <span className="text-xs font-semibold text-blue-700 dark:text-blue-300 uppercase">Executive summary</span>
        <p className="text-sm text-gray-800 dark:text-purple-100 mt-1 leading-relaxed">{report.executive_summary}</p>
      </div>
      {report.findings?.length > 0 && (
        <Section title="What was found">
          {report.findings.map((f, i) => (
            <div key={i} className="mt-2">
              <p className="text-sm text-gray-800 dark:text-purple-100">{f.what}</p>
              {f.evidence?.map((e, j) => (
                <p key={j} className="text-[11px] font-mono text-gray-500 dark:text-purple-300 break-words mt-0.5">{e}</p>
              ))}
            </div>
          ))}
        </Section>
      )}
      {report.what_is_happening && (
        <Section title="What is happening"><p className={TEXT}>{report.what_is_happening}</p></Section>
      )}
      {report.timeline?.length > 0 && (
        <Section title="Timeline">
          <ul className="mt-1 space-y-0.5">
            {report.timeline.map((t, i) => (
              <li key={i} className="text-sm text-gray-700 dark:text-purple-100">
                <span className="font-mono text-xs text-gray-500 dark:text-purple-300 mr-2">{t.time}</span>{t.event}
              </li>
            ))}
          </ul>
        </Section>
      )}
      <Section title="Ongoing or once">
        <p className={TEXT}><strong>{patternLabel(report.pattern)}.</strong> {report.pattern_explained}</p>
      </Section>
      {(report.known_issue || report.sources?.length > 0) && (
        <Section title="Known elsewhere">
          {report.known_issue && <p className={TEXT}>{report.known_issue}</p>}
          {report.sources?.map((s, i) => (
            <a key={i} href={s.uri} target="_blank" rel="noopener noreferrer nofollow"
               className="text-xs text-blue-700 dark:text-blue-300 hover:underline flex items-center gap-1 mt-1 break-all">
              <ExternalLink size={11} />{s.title || s.uri}
            </a>
          ))}
        </Section>
      )}
      <Section title="Conclusion and next step">
        {report.conclusion && <p className={TEXT}>{report.conclusion}</p>}
        {report.next_step && <p className={TEXT}><strong>Next step:</strong> {report.next_step}</p>}
      </Section>
      {report.followups?.length > 0 && (
        <Section title="Follow-ups">
          {report.followups.map((f, i) => (
            <p key={i} className={TEXT}>
              <span className="text-xs text-gray-500 dark:text-purple-300 mr-2">{hhmm(f.at)}</span>{f.summary}
            </p>
          ))}
        </Section>
      )}
      <p className="text-xs text-gray-500 dark:text-purple-300">
        Written {hhmm(report.written_at)}{report.requested_by ? ` for ${report.requested_by}` : ''}
        {` · ${report.lines_read ?? 0} log lines read`}
        {report.searched_web ? ' · web searched' : ' · no web search'}
      </p>
    </div>
  )
}

export default function InvestigationPanel({ alert, canAct, onReport }) {
  const [report, setReport] = useState(alert?.report || null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const ref = alarmRef(alert)

  useEffect(() => { setReport(alert?.report || null); setError(null) }, [alert])

  // While the investigation runs, read the alarm again until its report is written
  useEffect(() => {
    if (report?.status !== 'running') return undefined
    const id = setInterval(() => {
      const q = new URLSearchParams({ group: ref.group, ...(ref.node_id ? { node_id: ref.node_id } : {}) })
      apiFetch(`/api/alerts/one?${q}`)
        .then(a => { setReport(a.report || null); onReport?.(a) })
        .catch(() => {})
    }, 4000)
    return () => clearInterval(id)
  }, [report?.status, ref.group, ref.node_id])

  const post = (path, then) => {
    setBusy(true)
    setError(null)
    apiFetch(path, { method: 'POST', body: JSON.stringify(ref) })
      .then(then)
      .catch(err => setError(errorText(err)))
      .finally(() => setBusy(false))
  }
  const investigate = () => post('/api/alerts/investigate', () => setReport({ status: 'running' }))
  const followUp = () => post('/api/alerts/followup', entry =>
    setReport(r => ({ ...r, followups: [...(r?.followups || []), entry] })))

  const status = report?.status
  return (
    <div className="space-y-3 mb-4">
      {status === 'done' && <Report report={report} />}
      {status === 'running' && (
        <p className="text-sm text-gray-600 dark:text-purple-200 flex items-center gap-2">
          <RefreshCw size={14} className="animate-spin" />
          Investigating: reading the last day of logs of this part and the parts connected to it…
        </p>
      )}
      {status === 'failed' && (
        <p className="text-xs text-red-700 dark:text-red-400">The investigation could not be finished: {report.error}</p>
      )}
      {canAct && status !== 'running' && status !== 'done' && (
        <button onClick={investigate} disabled={busy} className={BUTTON}>
          <Search size={14} />{busy ? 'Starting…' : 'Investigate deeper'}
        </button>
      )}
      {canAct && status === 'done' && (
        <button onClick={followUp} disabled={busy} className={BUTTON}>
          <RefreshCw size={14} className={busy ? 'animate-spin' : ''} />
          {busy ? 'Checking the logs since…' : 'Follow up: what happened since?'}
        </button>
      )}
      {error && <p className="text-xs text-red-700 dark:text-red-400">{error}</p>}
    </div>
  )
}
