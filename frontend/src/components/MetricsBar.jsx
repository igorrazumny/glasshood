// File: frontend/src/components/MetricsBar.jsx
// Purpose: Bottom bar — key numbers from topology data

import { HardDrive } from 'lucide-react'
import { metricsNotRead } from '../utils/coldvaultMetrics'

// REQ-009: default text color flips to dark slate on light, purple-100 on dark.
function Metric({ icon: Icon, label, value, color = 'text-gray-700 dark:text-purple-100' }) {
  return (
    <div className="flex items-center gap-2">
      <Icon size={14} className="text-gray-500 dark:text-purple-300" />
      <span className="text-gray-500 dark:text-purple-300 text-sm">{label}</span>
      <span className={`text-sm font-medium ${color}`}>{value}</span>
    </div>
  )
}

export default function MetricsBar({ topology }) {
  if (!topology) return null

  const cv = topology.nodes?.find(n => n.id.startsWith('vm-')) || topology.nodes?.find(n => n.id === 'coldvault')

  const ram = cv?.metrics?.ram_percent
  const cvMetrics = topology.coldvault_metrics

  return (
    <div className="flex items-center justify-center gap-8 px-4 py-2 bg-card dark:bg-purple-900 border-t border-border dark:border-purple-700">
      <Metric
        icon={HardDrive}
        label="RAM"
        value={ram != null ? `${ram}%` : '-'}
        color={
          ram > 80 ? 'text-red-600 dark:text-red-400'
          : ram > 60 ? 'text-yellow-600 dark:text-yellow-400'
          : 'text-green-600 dark:text-green-400'
        }
      />
      {/* REQ-GHA-025 clause 5: say plainly when ColdVault's metrics were not read */}
      {cvMetrics && !cvMetrics.read && (
        <span className="text-xs text-gray-500 dark:text-purple-300">
          {metricsNotRead(cvMetrics)}
        </span>
      )}
    </div>
  )
}
