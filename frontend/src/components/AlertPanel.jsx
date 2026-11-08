// File: frontend/src/components/AlertPanel.jsx
// Purpose: Display active Layer 1 rule engine alerts
// REQ-GHA-027: only alarms whose condition holds now, each once, in plain words;
// recently resolved alarms and rules without data are listed underneath.
// REQ-GHA-028: alarms not yet trusted carry an "example" or "observation" tag.
// REQ-GHA-038: one collapsible list per severity level; colour only as a small mark.
// REQ-GHA-038 clause 4: the alarm area takes at most about half the panel's height; open
// lists share it, each scrolling on its own.

import { useState } from 'react'
import { AlertTriangle, CheckCircle, ChevronRight, ChevronDown } from 'lucide-react'
import { alarmTitle, alarmWhen, resolvedWhen, notCheckedNames, alarmTag, LEVELS, alarmsByLevel, defaultOpen } from '../utils/alarms'

const OPEN_KEY = 'glasshood.alarmLists'

function loadOpen() {
  try { return JSON.parse(localStorage.getItem(OPEN_KEY) || '{}') || {} } catch { return {} }
}

export default function AlertPanel({ alerts, resolved, rules, onSelect, systemOf }) {
  const [showResolved, setShowResolved] = useState(false)
  const [chosen, setChosen] = useState(loadOpen)   // what the reader opened or closed, remembered
  const notChecked = notCheckedNames(rules)
  if (!alerts?.length && !resolved?.length && !notChecked.length) return null
  alerts = alerts || []

  const byLevel = alarmsByLevel(alerts)
  const defaults = defaultOpen(byLevel)
  const isOpen = id => (id in chosen ? chosen[id] : defaults[id])
  const toggle = id => {
    const next = { ...chosen, [id]: !isOpen(id) }
    setChosen(next)
    try { localStorage.setItem(OPEN_KEY, JSON.stringify(next)) } catch { /* not remembered */ }
  }
  const counted = alerts.filter(a => a.kind !== 'example')
  // REQ-GHA-038 clause 4: at most about half the panel; while a list is open it keeps room
  // for its alarms however long the AI overview above is (that one is capped at half too)
  const anyOpen = LEVELS.some(l => byLevel[l.id]?.length && isOpen(l.id))

  return (
    <div className="bg-card dark:bg-purple-800 border border-border dark:border-purple-700 rounded-lg p-3 mb-3 flex flex-col min-h-0"
      style={{ maxHeight: '50%', minHeight: anyOpen ? '40%' : undefined, flex: '1 1 auto' }}>
      <div className="flex items-center justify-between mb-2 flex-shrink-0">
        <div className="flex items-center gap-2">
          <AlertTriangle size={14} className="text-gray-500 dark:text-purple-300" />
          <span className="text-xs font-semibold text-gray-500 dark:text-purple-300 uppercase tracking-wider">Alerts</span>
        </div>
        <span className="text-xs text-gray-500 dark:text-purple-300">{counted.length ? `${counted.length} open` : 'none open'}</span>
      </div>

      <div className="flex flex-col min-h-0 flex-1 gap-1">
        {LEVELS.filter(l => byLevel[l.id]?.length).map(level => {
          const list = byLevel[level.id]
          const open = isOpen(level.id)
          return (
            <div key={level.id} className={`flex flex-col ${open ? 'min-h-0 flex-1' : 'flex-shrink-0'}`}>
              <button onClick={() => toggle(level.id)}
                className="flex items-center gap-2 h-7 px-1 rounded text-sm text-gray-700 dark:text-purple-100 hover:bg-surface dark:hover:bg-purple-700/40">
                {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                <span className={`w-2 h-2 rounded-full ${level.dot}`} />
                <span className="font-medium">{level.label}</span>
                <span className="text-gray-500 dark:text-purple-300">· {list.length}</span>
              </button>
              {open && (
                <div className="space-y-1 overflow-y-auto min-h-0 flex-1 pl-1 pr-1 pb-1">
                  {list.map((alert, i) => (
                    <div key={`${alert.group}-${alert.node_id}-${i}`} onClick={() => onSelect?.(alert)}
                      className={`flex items-start gap-2 bg-surface/60 dark:bg-purple-900/40 border border-border dark:border-purple-700 rounded px-2 py-1.5 ${onSelect ? 'cursor-pointer hover:border-accent-500 dark:hover:border-purple-400' : ''}`}>
                      <span className={`mt-1.5 w-1.5 h-1.5 rounded-full flex-shrink-0 ${level.dot}`} />
                      <div className="min-w-0 flex-1">
                        <p className="text-sm text-gray-800 dark:text-purple-100 leading-snug">
                          {alarmTag(alert) && (
                            <span className="text-[10px] font-semibold uppercase mr-1.5 px-1 py-px rounded border border-gray-400 dark:border-purple-400 text-gray-600 dark:text-purple-200">
                              {alarmTag(alert)}
                            </span>
                          )}
                          {systemOf && systemOf(alert) && (
                            <span className="text-[10px] font-semibold mr-1.5 px-1 py-px rounded bg-gray-200 dark:bg-purple-700 text-gray-700 dark:text-purple-100">
                              {systemOf(alert)}
                            </span>
                          )}
                          {alarmTitle(alert)}
                        </p>
                        <p className="text-xs text-gray-500 dark:text-purple-300 mt-0.5">{alarmWhen(alert)}</p>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )
        })}
        {!alerts.length && (
          <p className="text-sm text-gray-500 dark:text-purple-300">No alarm is active now.</p>
        )}
      </div>

      {resolved?.length > 0 && (
        <div className="mt-2 flex-shrink-0">
          <button onClick={() => setShowResolved(v => !v)}
            className="text-xs text-gray-500 dark:text-purple-300 hover:underline">
            {showResolved ? 'Hide' : 'Show'} recently resolved ({resolved.length})
          </button>
          {showResolved && (
            <div className="space-y-1 mt-1 max-h-32 overflow-y-auto">
              {resolved.map((alert, i) => (
                <div key={`${alert.group}-${alert.node_id}-${alert.ended_at}-${i}`}
                  className="flex items-start gap-2 text-xs text-gray-600 dark:text-purple-200">
                  <CheckCircle size={11} className="text-green-600 dark:text-green-400 mt-0.5 flex-shrink-0" />
                  <span className="min-w-0 flex-1">{alarmTitle(alert)}</span>
                  <span className="text-gray-500 dark:text-purple-300 whitespace-nowrap">{resolvedWhen(alert)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {notChecked.length > 0 && (
        <p className="text-xs text-gray-500 dark:text-purple-300 mt-2 flex-shrink-0">
          Not checked (no data for this system): {notChecked.join(', ')}
        </p>
      )}
    </div>
  )
}
