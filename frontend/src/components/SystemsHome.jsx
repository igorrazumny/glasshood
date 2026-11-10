// File: frontend/src/components/SystemsHome.jsx
// Purpose: REQ-GHA-035 clause 2 — the home view: every monitored system side by side, each
// with its state in one plain line and its open alarms; a click opens that system.

import { Fragment, useState } from 'react'
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

export default function SystemsHome({ title = 'All systems', cards, line, onOpen, onOpenAlert, descriptions = {}, loading = false, loadError = null, descriptionsError = null, measuring = false }) {
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
      {/* REQ-GHA-047: one grid for both sections, so their columns align; as many equal columns as
          fit at about 320 px, never wrapped fixed boxes; an empty slot rather than a ragged edge */}
      <div className="grid gap-4 mx-auto items-stretch"
        style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(min(320px, 100%), 1fr))', maxWidth: 1600 }}>
        {groupedCards(cards).map(({ group, cards: groupCards }, i) => (
          <Fragment key={group.id}>
            <div className={`flex items-baseline gap-3 ${i ? 'mt-2' : ''}`} style={{ gridColumn: '1 / -1' }}>
              <h3 className="text-sm font-semibold uppercase tracking-wider text-gray-600 dark:text-purple-200">{group.label}</h3>
              {off ? <AiOfflineLine offline={off.offline} onOpenAlert={onOpenAlert} /> : <span className="text-xs text-gray-500 dark:text-purple-300">{portfolioLine(groupCards)}</span>}
            </div>
            {groupCards.map(c => <SystemCard key={c.id} card={c} about={descriptions[c.product]} loadError={descriptionsError} measuring={measuring} onOpen={onOpen} onOpenAlert={onOpenAlert} />)}
          </Fragment>
        ))}
      </div>
    </div>
  )
}

// REQ-GHA-037: what a business owner needs — state in one line, open alarms, the AI's view of
// the whole system, when it was checked — and a clear way in
// REQ-GHA-047 clause 2: every line of the card has a fixed height, so every card is the same size
function SystemCard({ card: c, about, loadError, measuring, onOpen, onOpenAlert }) {
  const a = assessmentLine(about, Date.now(), measuring)
  if (!about && loadError) a.text = loadFailed('The assessment', loadError)
  else if (loadError && !a.problem) a.problem = loadFailed('A newer assessment', loadError)
  // REQ-GHA-050 clause 4: on an out-of-date card the next-evaluation line replaces the update's own
  // failure text and job line; a failed read of the records is still said (REQ-GHA-037 clause 6)
  const updateFailed = a.stale && !loadError
  const note = a.stale ? [updateFailed ? null : a.problem, a.next].filter(Boolean).join(' · ') : [a.problem, a.job].filter(Boolean).join(' · ')
  return (
    // a div, not a button: it holds the alert's link and the closed last evaluation
    <div role="button" tabIndex={0} onClick={() => onOpen(c.id)}
      onKeyDown={e => { if ((e.key === 'Enter' || e.key === ' ') && e.target === e.currentTarget) { e.preventDefault(); onOpen(c.id) } }}
      style={{ containerType: 'inline-size' }}
      className="group cursor-pointer text-left flex flex-col h-full min-w-0 bg-card dark:bg-purple-800 border border-border dark:border-purple-700 rounded-xl p-5
        hover:border-accent-500 dark:hover:border-purple-400 hover:shadow-lg hover:-translate-y-0.5 transition">
      <div className="flex items-center gap-2 h-10">
        {/* the white plate keeps the logo's own colours readable on the dark theme */}
        {c.logo
          ? <span className="bg-white rounded px-1.5 py-1 inline-flex"><img src={c.logo} alt={c.label} className="h-8 w-auto" /></span>
          : <span className="text-base font-bold text-gray-900 dark:text-purple-50 truncate">{c.label}</span>}
        {c.outside && (
          <span className="ml-auto text-xs text-gray-500 dark:text-purple-300 whitespace-nowrap"
            title="Built only from what the provider publishes; GlassHood has no access inside it">
            Provider status page
          </span>
        )}
      </div>
      <div className="text-xs text-gray-500 dark:text-purple-300 mt-0.5 h-4 truncate">
        {c.sourceUrl
          ? <a href={c.sourceUrl} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()} className="underline">{c.source}</a>
          : (c.outside ? c.source : c.subtitle)}
      </div>
      <div className="mt-3 h-6 flex items-center min-w-0">
        {c.offline ? <AiOfflineLine compact offline={c.offline} onOpenAlert={onOpenAlert} /> : <span className="truncate"><StatusChip card={c} /></span>}
      </div>
      <p className={`mt-1 text-sm h-5 truncate ${c.notice ? 'font-medium text-red-700 dark:text-red-400' : 'text-gray-700 dark:text-purple-200'}`}
        title={c.notice ? `Critical: ${c.notice}` : undefined}>
        {c.notice ? `Critical: ${c.notice}` : c.offline ? '' : c.line}
      </p>
      <div className="mt-3 pt-3 border-t border-border/70 dark:border-purple-700/70 flex-1 min-h-[6.5rem]">
        {/* the offline card has the same slots as a normal one, so closed cards stay equal in height */}
        {c.offline ? (
          <>
            <div className="text-[11px] font-semibold uppercase tracking-wider text-gray-500 dark:text-purple-300 mb-1 flex min-w-0">
              <span className="truncate" title={a.when || undefined}>{a.when && about?.summary ? (a.stale ? a.when.replace(/^evaluated /, '') : `Last evaluation · ${a.when}`) : 'Not evaluated yet'}</span>
              <StaleMark mark={a.stale} />
            </div>
            {/* REQ-GHA-050 clause 4: AI evaluation is offline, so no new one is running */}
            <div className="text-xs h-4 truncate text-gray-500 dark:text-purple-300">{a.stale ? 'Waiting for a new evaluation.' : ''}</div>
            <Assessment text={about?.summary || ''} busy={false} />
          </>
        ) : (
          <>
            <div className="text-[11px] font-semibold uppercase tracking-wider text-gray-500 dark:text-purple-300 mb-1 flex min-w-0">
              {/* REQ-GHA-050 clauses 1 and 3: beside the mark only the date and time, so both stay readable */}
              <span className="truncate" title={a.when || undefined}>{a.stale ? a.when.replace(/^evaluated /, '') : `AI assessment${a.when ? ` · ${a.when}` : ''}`}</span>
              <StaleMark mark={a.stale} />
            </div>
            <div className={`text-xs h-4 truncate ${a.problem && !updateFailed ? 'text-red-700 dark:text-red-400' : 'text-gray-500 dark:text-purple-300'}`} title={note || undefined}>{note}</div>
            <Assessment text={a.text} busy={a.busy && !a.job && !loadError} />
          </>
        )}
      </div>
      <div className="mt-4 flex items-center justify-end text-xs text-gray-500 dark:text-purple-300">
        <span className="text-sm font-medium text-accent-600 dark:text-accent-300 group-hover:translate-x-0.5 transition">See details →</span>
      </div>
    </div>
  )
}

// REQ-GHA-050 clause 3: the amber mark beside the evaluation line; it never shrinks, the time is clipped first
function StaleMark({ mark }) {
  return mark ? <span title={mark} className="ml-1.5 flex-shrink-0 normal-case tracking-normal text-amber-700 dark:text-amber-300">· {mark}</span> : null
}

// REQ-GHA-045 clause 4: one line until the reader asks for the whole assessment
function Assessment({ text, busy }) {
  const [open, setOpen] = useState(false)
  return (
    <div>
      {/* REQ-GHA-047 clauses 2 and 3: two lines, two lines of height, the full text on request */}
      <p className={`text-sm text-gray-700 dark:text-purple-100 leading-[1.55] max-w-[65ch] min-h-[2.72rem] ${open ? '' : 'line-clamp-2'}`}>
        {busy && <Loader2 size={14} className="inline animate-spin mr-1 -mt-0.5" />}
        {text}
      </p>
      <div className="h-4 mt-1">
        {!busy && text && (
          <button type="button" onClick={e => { e.stopPropagation(); setOpen(!open) }}
            className="text-xs font-medium text-accent-600 dark:text-accent-300 underline">
            {open ? 'Hide assessment' : 'Read assessment'}
          </button>
        )}
      </div>
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
