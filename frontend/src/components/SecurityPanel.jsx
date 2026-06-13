// File: frontend/src/components/SecurityPanel.jsx
// Purpose: Display CVE security findings from the scanner

import { useState, useEffect } from 'react'
import { Shield, ShieldAlert, ShieldCheck, ChevronDown, ChevronUp } from 'lucide-react'

// REQ-009: severity + status pill pairs — light uses bg-100 + text-700,
// dark uses bg-400/10 + text-400 so CVE rows read on both themes.
const SEVERITY_STYLE = {
  critical: {
    color: 'text-red-700 dark:text-red-400',
    bg: 'bg-red-100 dark:bg-red-400/10',
    border: 'border-red-300 dark:border-red-400/20' },
  high: {
    color: 'text-orange-700 dark:text-orange-400',
    bg: 'bg-orange-100 dark:bg-orange-400/10',
    border: 'border-orange-300 dark:border-orange-400/20' },
  medium: {
    color: 'text-yellow-700 dark:text-yellow-400',
    bg: 'bg-yellow-100 dark:bg-yellow-400/10',
    border: 'border-yellow-300 dark:border-yellow-400/20' },
  low: {
    color: 'text-gray-600 dark:text-gray-400',
    bg: 'bg-gray-100 dark:bg-gray-400/10',
    border: 'border-gray-300 dark:border-gray-400/20' },
}

const STATUS_BADGE = {
  open: { label: 'Open', color: 'text-red-700 bg-red-100 dark:text-red-400 dark:bg-red-400/10' },
  acknowledged: { label: 'Ack', color: 'text-yellow-700 bg-yellow-100 dark:text-yellow-400 dark:bg-yellow-400/10' },
  mitigated: { label: 'Mitigated', color: 'text-green-700 bg-green-100 dark:text-green-400 dark:bg-green-400/10' },
  accepted: { label: 'Accepted', color: 'text-blue-700 bg-blue-100 dark:text-blue-400 dark:bg-blue-400/10' },
}

export default function SecurityPanel({ isDemo }) {
  const [findings, setFindings] = useState([])
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    if (isDemo) return
    const fetchFindings = () => {
      const token = localStorage.getItem('token')
      if (!token) return
      fetch('/api/security/findings', {
        headers: { Authorization: `Bearer ${token}` }
      })
        .then(r => r.ok ? r.json() : null)
        .then(data => { if (data) setFindings(data.findings || []) })
        .catch(() => {})
    }
    fetchFindings()
    const interval = setInterval(fetchFindings, 60000)
    return () => clearInterval(interval)
  }, [isDemo])

  if (!findings.length) return null

  const criticalCount = findings.filter(f => f.severity === 'critical').length
  const highCount = findings.filter(f => f.severity === 'high').length
  const openCount = findings.filter(f => f.status === 'open').length

  // Group by component, sort by CVSS
  const sorted = [...findings].sort((a, b) => b.cvss_score - a.cvss_score)
  const displayed = expanded ? sorted : sorted.slice(0, 3)

  return (
    <div className="bg-card dark:bg-purple-800 border border-border dark:border-purple-700 rounded-lg p-3 mb-3">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <ShieldAlert size={14} className="text-orange-600 dark:text-orange-400" />
          <span className="text-xs font-semibold text-gray-500 dark:text-purple-300 uppercase tracking-wider">CVE Findings</span>
        </div>
        <div className="flex items-center gap-2 text-sm">
          {criticalCount > 0 && <span className="text-red-700 dark:text-red-400">{criticalCount} critical</span>}
          {highCount > 0 && <span className="text-orange-700 dark:text-orange-400">{highCount} high</span>}
          <span className="text-gray-500 dark:text-purple-300">{openCount} open</span>
        </div>
      </div>

      <div className="space-y-1.5 max-h-48 overflow-y-auto">
        {displayed.map((f, i) => {
          const style = SEVERITY_STYLE[f.severity] || SEVERITY_STYLE.low
          const badge = STATUS_BADGE[f.status] || STATUS_BADGE.open
          return (
            <div key={`${f.cve_id}-${i}`}
              className={`${style.bg} ${style.border} border rounded px-2 py-1.5`}>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  {f.gxp_critical
                    ? <ShieldAlert size={11} className={style.color} />
                    : <Shield size={11} className={style.color} />}
                  <span className={`text-sm font-mono ${style.color}`}>{f.cve_id}</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="text-sm text-gray-500 dark:text-purple-300">CVSS {f.cvss_score}</span>
                  <span className={`text-xs px-1 rounded ${badge.color}`}>{badge.label}</span>
                </div>
              </div>
              <p className="text-sm text-gray-600 dark:text-purple-200 mt-0.5 leading-snug truncate">{f.component_name}</p>
            </div>
          )
        })}
      </div>

      {sorted.length > 3 && (
        <button onClick={() => setExpanded(!expanded)}
          className="w-full mt-1.5 text-xs text-gray-500 hover:text-gray-700 dark:text-purple-300 dark:hover:text-purple-100 flex items-center justify-center gap-1">
          {expanded ? <><ChevronUp size={12} /> Show less</> : <><ChevronDown size={12} /> {sorted.length - 3} more</>}
        </button>
      )}
    </div>
  )
}
