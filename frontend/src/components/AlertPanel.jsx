// File: frontend/src/components/AlertPanel.jsx
// Purpose: Display active Layer 1 rule engine alerts

import { AlertTriangle, AlertOctagon, Info } from 'lucide-react'

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

function timeAgo(isoStr) {
  const seconds = Math.round((Date.now() - new Date(isoStr).getTime()) / 1000)
  if (seconds < 60) return `${seconds}s ago`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  return `${Math.floor(seconds / 3600)}h ago`
}

export default function AlertPanel({ alerts, onSelect }) {
  if (!alerts?.length) return null

  // Sort: critical first, then warning, then info
  const order = { critical: 0, warning: 1, info: 2 }
  const sorted = [...alerts].sort((a, b) => (order[a.severity] ?? 3) - (order[b.severity] ?? 3))

  const criticalCount = alerts.filter(a => a.severity === 'critical').length
  const warningCount = alerts.filter(a => a.severity === 'warning').length

  return (
    <div className="bg-card dark:bg-purple-800 border border-border dark:border-purple-700 rounded-lg p-3 mb-3">
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

      <div className="space-y-1.5 max-h-48 overflow-y-auto">
        {sorted.map((alert, i) => {
          const style = SEVERITY_STYLE[alert.severity] || SEVERITY_STYLE.info
          const Icon = style.icon
          return (
            <div key={`${alert.rule_id}-${alert.node_id}-${i}`}
              onClick={() => onSelect?.(alert)}
              className={`flex items-start gap-2 ${style.bg} ${style.border} border rounded px-2 py-1.5 ${onSelect ? 'cursor-pointer hover:brightness-95 dark:hover:brightness-125' : ''}`}>
              <Icon size={12} className={`${style.color} mt-0.5 flex-shrink-0`} />
              <div className="min-w-0 flex-1">
                <p className={`text-sm ${style.color} leading-snug`}>{alert.message}</p>
                <p className="text-xs text-gray-500 dark:text-purple-300 mt-0.5">{timeAgo(alert.triggered_at)}</p>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
