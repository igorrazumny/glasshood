// File: frontend/src/components/AlertPanel.jsx
// Purpose: Display active Layer 1 rule engine alerts
// REQ-GHA-027: only alarms whose condition holds now, each once, in plain words;
// recently resolved alarms and rules without data are listed underneath.
// REQ-GHA-028: alarms not yet trusted carry an "example" or "observation" tag.
// REQ-GHA-033 clause 4: the list takes all the height left in the right panel and
// scrolls only when the alarms do not fit.

import { useState } from 'react'
import { AlertTriangle, AlertOctagon, Info, CheckCircle } from 'lucide-react'
import { alarmTitle, alarmWhen, resolvedWhen, notCheckedNames, alarmTag, sortAlarms } from '../utils/alarms'

// REQ-009: severity styles get dark: variants. Light uses bg-100 + text-700
// for readable contrast on white card; dark keeps the /10 alpha + light text.
const SEVERITY_STYLE = {
  critical: { icon: AlertOctagon,
    color: 'text-red-700 dark:text-red-400',
    bg: 'bg-red-100 dark:bg-red-400/10',
    border: 'border-red-300 dark:border-red-400/20' },
  warning: { icon: AlertTriangle,
    color: 'text-yellow-700 dark:text-yellow-400',
    bg: 'bg-yellow-100 dark:bg-yellow-400/10',
    border: 'border-yellow-300 dark:border-yellow-400/20' },
  info: { icon: Info,
    color: 'text-blue-700 dark:text-blue-400',
    bg: 'bg-blue-100 dark:bg-blue-400/10',
    border: 'border-blue-300 dark:border-blue-400/20' },
}

export default function AlertPanel({ alerts, resolved, rules, onSelect, systemOf }) {
  const [showResolved, setShowResolved] = useState(false)
  const notChecked = notCheckedNames(rules)
  if (!alerts?.length && !resolved?.length && !notChecked.length) return null
  alerts = alerts || []

  // Critical first, then warning; real alarms before examples (REQ-GHA-028)
  const sorted = sortAlarms(alerts)

  const criticalCount = alerts.filter(a => a.severity === 'critical').length
  const warningCount = alerts.filter(a => a.severity === 'warning').length

  return (
    <div className="bg-card dark:bg-purple-800 border border-border dark:border-purple-700 rounded-lg p-3 mb-3 flex-1 min-h-[16rem] flex flex-col">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <AlertTriangle size={14} className="text-yellow-600 dark:text-yellow-400" />
          <span className="text-xs font-semibold text-gray-500 dark:text-purple-300 uppercase tracking-wider">Alerts</span>
        </div>
        <div className="flex items-center gap-2 text-sm">
          {criticalCount > 0 && (
            <span className="text-red-700 dark:text-red-400">{criticalCount} critical</span>
          )}
          {warningCount > 0 && (
            <span className="text-yellow-700 dark:text-yellow-400">{warningCount} warning</span>
          )}
        </div>
      </div>

      <div className="space-y-1.5 flex-1 min-h-0 overflow-y-auto">
        {sorted.map((alert, i) => {
          const style = SEVERITY_STYLE[alert.severity] || SEVERITY_STYLE.info
          const Icon = style.icon
          return (
            <div key={`${alert.rule_id}-${alert.node_id}-${i}`}
              onClick={() => onSelect?.(alert)}
              className={`flex items-start gap-2 ${style.bg} ${style.border} border rounded px-2 py-1.5 ${onSelect ? 'cursor-pointer hover:brightness-95 dark:hover:brightness-125' : ''}`}>
              <Icon size={12} className={`${style.color} mt-0.5 flex-shrink-0`} />
              <div className="min-w-0 flex-1">
                <p className={`text-sm ${style.color} leading-snug`}>
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
          )
        })}
        {!alerts.length && (
          <p className="text-sm text-gray-500 dark:text-purple-300">No alarm is active now.</p>
        )}
      </div>

      {resolved?.length > 0 && (
        <div className="mt-2">
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
        <p className="text-xs text-gray-500 dark:text-purple-300 mt-2">
          Not checked (no data for this system): {notChecked.join(', ')}
        </p>
      )}
    </div>
  )
}
