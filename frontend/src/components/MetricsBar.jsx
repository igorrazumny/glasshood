// File: frontend/src/components/MetricsBar.jsx
// Purpose: Bottom bar — key numbers from topology data

import { Clock, Activity, HardDrive, Users } from 'lucide-react'

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

function formatUptime(seconds) {
  if (!seconds) return '-'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}

export default function MetricsBar({ topology }) {
  if (!topology) return null

  const cv = topology.nodes?.find(n => n.id.startsWith('vm-')) || topology.nodes?.find(n => n.id === 'coldvault')
  const lb = topology.nodes?.find(n => n.id.startsWith('fr-')) || topology.nodes?.find(n => n.id === 'lb')

  const uptime = cv?.metrics?.uptime_s
  const ram = cv?.metrics?.ram_percent
  const reqs = lb?.metrics?.requests_1h
  const users = topology.user_stats?.active_users

  return (
    <div className="flex items-center justify-center gap-8 px-4 py-2 bg-card dark:bg-purple-900 border-t border-border dark:border-purple-700">
      <Metric icon={Clock} label="Uptime" value={formatUptime(uptime)} />
      <Metric
        icon={Activity}
        label="Requests/1h"
        value={reqs ?? '-'}
      />
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
      <Metric
        icon={Users}
        label="Active Users"
        value={users ?? '-'}
      />
    </div>
  )
}
