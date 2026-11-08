// File: frontend/src/components/SystemsHome.jsx
// Purpose: REQ-GHA-035 clause 2 — the home view: every monitored system side by side, each
// with its state in one plain line and its open alarms; a click opens that system.

import { AlertOctagon, AlertTriangle, Eye, Loader2 } from 'lucide-react'
import { clock } from '../utils/time'
import { assessmentLine, loadFailed } from '../utils/systems'
import { groupedCards, portfolioLine } from '../utils/systems'

const DOT = {
  healthy: 'bg-green-500', degraded: 'bg-yellow-500', error: 'bg-red-500',
  'not checked': 'bg-gray-400',
}

export default function SystemsHome({ cards, line, onOpen, descriptions = {}, loading = false, loadError = null, descriptionsError = null }) {
  // REQ-GHA-035 clause 9: 9Robots systems and external systems, each with its own line
  // REQ-GHA-037 clause 6: while the systems load, say so
  if (!cards.length && loadError) return <Failed text={loadFailed('Your systems', loadError)} />
  if (loading && !cards.length) return <Waiting text="Loading your systems…" />
  return (
    <div className="h-full overflow-y-auto p-4">
      <div className="mb-4">
        <h2 className="text-lg font-semibold text-gray-800 dark:text-purple-100">Monitored systems</h2>
        <p className="text-sm text-gray-500 dark:text-purple-300">{line}</p>
      </div>
      {groupedCards(cards).map(({ group, cards: groupCards }) => (
        <section key={group.id} className="mb-6">
          <div className="flex items-baseline gap-3 mb-2">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-gray-600 dark:text-purple-200">{group.label}</h3>
            <span className="text-xs text-gray-500 dark:text-purple-300">{portfolioLine(groupCards)}</span>
          </div>
          <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))' }}>
            {groupCards.map(c => <SystemCard key={c.id} card={c} about={descriptions[c.product]} loadError={descriptionsError} onOpen={onOpen} />)}
          </div>
        </section>
      ))}
    </div>
  )
}

// REQ-GHA-037: what a business owner needs — state in one line, open alarms, the AI's view of
// the whole system, when it was checked — and a clear way in
function SystemCard({ card: c, about, loadError, onOpen }) {
  const a = assessmentLine(about, Date.now())
  if (!about && loadError) a.text = loadFailed('The assessment', loadError)
  else if (loadError && !a.problem) a.problem = loadFailed('A newer assessment', loadError)
  return (
    <button onClick={() => onOpen(c.id)}
      className="group text-left flex flex-col bg-card dark:bg-purple-800 border border-border dark:border-purple-700 rounded-xl p-5
        hover:border-accent-500 dark:hover:border-purple-400 hover:shadow-lg hover:-translate-y-0.5 transition">
      <div className="flex items-center gap-2">
        <span className={`w-2.5 h-2.5 rounded-full ${DOT[c.state] || DOT['not checked']}`} />
        <span className="text-lg font-semibold text-gray-900 dark:text-purple-50">{c.label}</span>
        {c.outside && (
          <span className="ml-auto flex items-center gap-1 text-[10px] uppercase tracking-wide px-1.5 py-px rounded border border-gray-300 dark:border-purple-500 text-gray-500 dark:text-purple-300"
            title="Built only from what the provider publishes; GlassHood has no access inside it">
            <Eye size={10} /> Outside view
          </span>
        )}
      </div>
      {(c.outside ? c.source : c.subtitle) && <div className="text-xs text-gray-500 dark:text-purple-300 mt-0.5">{c.outside ? c.source : c.subtitle}</div>}
      <p className="text-[15px] font-medium text-gray-800 dark:text-purple-100 mt-3">{c.line}</p>
      <div className="flex items-center gap-3 mt-1 text-sm">
        {c.critical + c.warning > 0
          ? <span className={`flex items-center gap-1 ${c.critical ? 'text-red-700 dark:text-red-400' : 'text-yellow-700 dark:text-yellow-400'}`}>
              {c.critical ? <AlertOctagon size={13} /> : <AlertTriangle size={13} />}
              {c.critical + c.warning} alert{c.critical + c.warning === 1 ? '' : 's'} to review{c.critical ? ` (${c.critical} critical)` : ''}
            </span>
          : <span className="text-gray-500 dark:text-purple-300">No active alerts</span>}
        {c.notes > 0 && <span className="text-gray-500 dark:text-purple-300">{c.notes} configuration note{c.notes === 1 ? '' : 's'}</span>}
      </div>
      <div className="mt-3 pt-3 border-t border-border/70 dark:border-purple-700/70 flex-1">
        <div className="text-[11px] font-semibold uppercase tracking-wider text-gray-500 dark:text-purple-300 mb-1">
          AI assessment{a.when ? ` · ${a.when}` : ''}
        </div>
        {a.old && (
          <div className="text-xs text-yellow-700 dark:text-yellow-400 mb-1">{a.old}</div>
        )}
        {a.problem && (
          <div className="text-xs text-red-700 dark:text-red-400 mb-1">{a.problem}</div>
        )}
        <p className="text-sm text-gray-700 dark:text-purple-100 leading-relaxed flex items-start gap-2">
          {a.busy && !loadError && <Loader2 size={14} className="animate-spin mt-0.5 flex-shrink-0" />}
          <span>{a.text}</span>
        </p>
      </div>
      <div className="mt-4 flex items-center justify-between text-xs text-gray-500 dark:text-purple-300">
        <span>{c.checkedAt ? `Checked ${clock(c.checkedAt * 1000)}` : 'Not checked yet'}</span>
        <span className="text-sm font-medium text-accent-600 dark:text-accent-300 group-hover:translate-x-0.5 transition">See details →</span>
      </div>
    </button>
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
