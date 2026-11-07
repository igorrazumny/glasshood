// File: frontend/src/components/SystemsHome.jsx
// Purpose: REQ-GHA-035 clause 2 — the home view: every monitored system side by side, each
// with its state in one plain line and its open alarms; a click opens that system.

import { AlertOctagon, AlertTriangle, Eye } from 'lucide-react'
import { clock } from '../utils/time'
import { groupedCards, portfolioLine } from '../utils/systems'

const DOT = {
  healthy: 'bg-green-500', degraded: 'bg-yellow-500', error: 'bg-red-500',
  'not checked': 'bg-gray-400',
}

export default function SystemsHome({ cards, line, onOpen }) {
  // REQ-GHA-035 clause 9: 9Robots systems and external systems, each with its own line
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
          <SystemGrid cards={groupCards} onOpen={onOpen} />
        </section>
      ))}
    </div>
  )
}

function SystemGrid({ cards, onOpen }) {
  return (
      <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))' }}>
        {cards.map(c => (
          <button key={c.id} onClick={() => onOpen(c.id)}
            className="text-left bg-card dark:bg-purple-800 border border-border dark:border-purple-700 rounded-lg p-4 hover:border-blue-400 dark:hover:border-purple-400 hover:shadow transition">
            <div className="flex items-center gap-2">
              <span className={`w-2.5 h-2.5 rounded-full ${DOT[c.state] || DOT['not checked']}`} />
              <span className="font-semibold text-gray-800 dark:text-purple-100">{c.label}</span>
              {c.outside && (
                <span className="ml-auto flex items-center gap-1 text-[10px] uppercase tracking-wide px-1.5 py-px rounded border border-gray-300 dark:border-purple-500 text-gray-500 dark:text-purple-300"
                  title="Built only from what the provider publishes; GlassHood has no access inside it">
                  <Eye size={10} /> Outside view
                </span>
              )}
            </div>
            {c.subtitle && <div className="text-xs text-gray-500 dark:text-purple-300 mt-0.5">{c.subtitle}</div>}
            <p className="text-sm text-gray-700 dark:text-purple-100 mt-2">{c.line}</p>
            <div className="flex items-center gap-3 mt-2 text-sm">
              {c.critical > 0 && <span className="flex items-center gap-1 text-red-700 dark:text-red-400"><AlertOctagon size={13} />{c.critical} critical</span>}
              {c.warning > 0 && <span className="flex items-center gap-1 text-yellow-700 dark:text-yellow-400"><AlertTriangle size={13} />{c.warning} warning</span>}
              {!c.critical && !c.warning && <span className="text-gray-500 dark:text-purple-300">No open alarm</span>}
            </div>
            <div className="text-xs text-gray-500 dark:text-purple-300 mt-2">
              {c.parts} part{c.parts === 1 ? '' : 's'}{c.checkedAt ? ` · checked ${clock(c.checkedAt * 1000)}` : ''}
            </div>
          </button>
        ))}
      </div>
  )
}
