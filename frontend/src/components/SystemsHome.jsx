// File: frontend/src/components/SystemsHome.jsx
// Purpose: REQ-GHA-035 clause 2 — the home view: every monitored system side by side, each
// with its state in one plain line and its open alarms; a click opens that system.

import { useState } from 'react'
import { AlertOctagon, AlertTriangle, CheckCircle, HelpCircle, Loader2 } from 'lucide-react'
import { assessmentLine, loadFailed, statusWord, statusReason } from '../utils/systems'
import AiOfflineLine from './AiOfflineLine'
import { groupedCards, portfolioLine } from '../utils/systems'

const CHIP = {
  healthy: ['text-green-700 dark:text-green-400', CheckCircle],
  degraded: ['text-yellow-700 dark:text-yellow-400', AlertTriangle],
  error: ['text-red-700 dark:text-red-400', AlertOctagon],
}

// REQ-GHA-045 clause 5: icon and word, the reason straight after
function StatusChip({ card }) {
  const [color, Icon] = CHIP[card.state] || ['text-gray-500 dark:text-purple-300', HelpCircle]
  const reason = statusReason(card)
  return (
    <span className={`inline-flex items-center gap-1 text-[15px] font-bold ${color}`}>
      <Icon size={15} />{statusWord(card.state)}{reason && <span> · {reason}</span>}
    </span>
  )
}

export default function SystemsHome({ title = 'All systems', cards, line, onOpen, onOpenAlert, descriptions = {}, loading = false, loadError = null, descriptionsError = null }) {
  // REQ-GHA-035 clause 9: Proprietary systems and External systems, each with its own line
  // REQ-GHA-037 clause 6: while the systems load, say so
  if (!cards.length && loadError) return <Failed text={loadFailed('Your systems', loadError)} />
  if (loading && !cards.length) return <Waiting text="Loading your systems…" />
  const off = cards.find(c => c.offline)   // REQ-GHA-042: the group summaries say it too
  return (
    <div className="h-full overflow-y-auto p-4">
      <div className="mb-4">
        <h2 className="text-[22px] font-bold text-gray-800 dark:text-purple-100">{title}</h2>
        <p className="text-sm text-gray-500 dark:text-purple-300">{off ? <AiOfflineLine offline={off.offline} onOpenAlert={onOpenAlert} /> : line}</p>
      </div>
      {groupedCards(cards).map(({ group, cards: groupCards }) => (
        <section key={group.id} className="mb-6">
          <div className="flex items-baseline gap-3 mb-2">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-gray-600 dark:text-purple-200">{group.label}</h3>
            {off ? <AiOfflineLine offline={off.offline} onOpenAlert={onOpenAlert} /> : <span className="text-xs text-gray-500 dark:text-purple-300">{portfolioLine(groupCards)}</span>}
          </div>
          {/* only the cards a group really has take space: they grow into spare width up to a
              comfortable maximum, then narrow, then stack */}
          <div className="flex flex-wrap gap-4">
            {groupCards.map(c => <SystemCard key={c.id} card={c} about={descriptions[c.product]} loadError={descriptionsError} onOpen={onOpen} onOpenAlert={onOpenAlert} />)}
          </div>
        </section>
      ))}
    </div>
  )
}

// REQ-GHA-037: what a business owner needs — state in one line, open alarms, the AI's view of
// the whole system, when it was checked — and a clear way in
function SystemCard({ card: c, about, loadError, onOpen, onOpenAlert }) {
  const a = assessmentLine(about, Date.now())
  if (!about && loadError) a.text = loadFailed('The assessment', loadError)
  else if (loadError && !a.problem) a.problem = loadFailed('A newer assessment', loadError)
  return (
    // a div, not a button: it holds the alert's link and the closed last evaluation
    <div role="button" tabIndex={0} onClick={() => onOpen(c.id)}
      onKeyDown={e => { if ((e.key === 'Enter' || e.key === ' ') && e.target === e.currentTarget) { e.preventDefault(); onOpen(c.id) } }}
      style={{ flex: '1 1 320px', minWidth: 0, maxWidth: 520 }}
      className="group cursor-pointer text-left flex flex-col bg-card dark:bg-purple-800 border border-border dark:border-purple-700 rounded-xl p-5
        hover:border-accent-500 dark:hover:border-purple-400 hover:shadow-lg hover:-translate-y-0.5 transition">
      <div className="flex items-center gap-2">
        {/* the white plate keeps the logo's own colours readable on the dark theme */}
        {c.logo
          ? <span className="bg-white rounded px-1.5 py-1 inline-flex"><img src={c.logo} alt={c.label} className="h-8 w-auto" /></span>
          : <span className="text-base font-bold text-gray-900 dark:text-purple-50">{c.label}</span>}
        {c.outside && (
          <span className="ml-auto text-xs text-gray-500 dark:text-purple-300"
            title="Built only from what the provider publishes; GlassHood has no access inside it">
            Provider status page
          </span>
        )}
      </div>
      {(c.outside ? c.source : c.subtitle) && <div className="text-xs text-gray-500 dark:text-purple-300 mt-0.5">
        {c.sourceUrl
          ? <a href={c.sourceUrl} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()} className="underline">{c.source}</a>
          : (c.outside ? c.source : c.subtitle)}
      </div>}
      {c.offline
        ? <p className="mt-3"><AiOfflineLine offline={c.offline} onOpenAlert={onOpenAlert} /></p>
        : <p className="mt-3"><StatusChip card={c} /></p>}
      {!c.offline && (
      <p className="mt-1 text-sm text-gray-700 dark:text-purple-200">{c.line}</p>
      )}
      {c.notice && <p className="text-sm font-medium text-red-700 dark:text-red-400 mt-2">Critical: {c.notice}</p>}
      {c.offline ? (
        <details className="mt-3 pt-3 border-t border-border/70 dark:border-purple-700/70 flex-1" onClick={e => e.stopPropagation()}>
          <summary className="text-xs font-semibold text-gray-500 dark:text-purple-300 cursor-pointer">
            {a.when && about?.summary ? `Last evaluation, ${a.when.replace(/^evaluated /, '')}` : 'Not evaluated yet'}
          </summary>
          {about?.summary && <p className="text-sm text-gray-700 dark:text-purple-100 leading-relaxed mt-1">{about.summary}</p>}
        </details>
      ) : (
      <div className="mt-3 pt-3 border-t border-border/70 dark:border-purple-700/70 flex-1">
        <div className="text-[11px] font-semibold uppercase tracking-wider text-gray-500 dark:text-purple-300 mb-1">
          AI assessment{a.when ? ` · ${a.when}` : ''}
        </div>
        {a.problem && (
          <div className="text-xs text-red-700 dark:text-red-400 mb-1">{a.problem}</div>
        )}
        {a.job && <div className="text-xs text-gray-500 dark:text-purple-300 mb-1">{a.job}</div>}
        <Assessment text={a.text} busy={a.busy && !a.job && !loadError} />
      </div>
      )}
      <div className="mt-4 flex items-center justify-end text-xs text-gray-500 dark:text-purple-300">
        <span className="text-sm font-medium text-accent-600 dark:text-accent-300 group-hover:translate-x-0.5 transition">See details →</span>
      </div>
    </div>
  )
}

// REQ-GHA-045 clause 4: one line until the reader asks for the whole assessment
function Assessment({ text, busy }) {
  const [open, setOpen] = useState(false)
  return (
    <div>
      <p className={`text-sm text-gray-700 dark:text-purple-100 leading-[1.55] max-w-[65ch] flex items-start gap-2 ${open ? '' : 'min-w-0'}`}>
        {busy && <Loader2 size={14} className="animate-spin mt-0.5 flex-shrink-0" />}
        <span className={open ? '' : 'truncate'}>{text}</span>
      </p>
      {!busy && text && (
        <button type="button" onClick={e => { e.stopPropagation(); setOpen(!open) }}
          className="mt-1 text-xs font-medium text-accent-600 dark:text-accent-300 underline">
          {open ? 'Hide assessment' : 'Read assessment'}
        </button>
      )}
    </div>
  )
}

export function Failed({ text }) {
  return (
    <div className="h-full flex items-center justify-center p-6">
      <span className="text-sm text-yellow-700 dark:text-yellow-300 text-center">{text}</span>
    </div>
  )
}

export function Waiting({ text }) {
  return (
    <div className="h-full flex flex-col items-center justify-center gap-3 text-gray-500 dark:text-purple-300">
      <Loader2 size={28} className="animate-spin" />
      <span className="text-sm">{text}</span>
    </div>
  )
}
