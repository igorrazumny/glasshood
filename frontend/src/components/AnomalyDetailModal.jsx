// File: frontend/src/components/AnomalyDetailModal.jsx
// Purpose: Detail modal for anomalies — z-score, baseline, confidence explanation

import { X, TrendingUp } from 'lucide-react'

function confidenceExplanation(confidence) {
  const pct = Math.round((confidence || 0) * 100)
  if (pct >= 90) return 'Very high confidence — value is extremely far from normal baseline'
  if (pct >= 70) return 'High confidence — value significantly deviates from baseline'
  if (pct >= 50) return 'Moderate confidence — notable deviation, may warrant investigation'
  return 'Low confidence — minor deviation, likely within normal variation'
}

function severityExplanation(severity, confidence) {
  const pct = Math.round((confidence || 0) * 100)
  if (severity === 'critical') return `Critical anomaly (${pct}% confidence) — requires immediate investigation`
  return `Warning-level anomaly (${pct}% confidence) — monitor and investigate if persistent`
}

export default function AnomalyDetailModal({ anomaly, onClose }) {
  if (!anomaly) return null

  const pct = Math.round((anomaly.confidence || 0) * 100)
  // REQ-009: bar/severity colors get light + dark: pairs. Confidence bar
  // track flips from bg-gray-700 (dark-only) to bg-gray-200 dark:bg-purple-700.
  const barColor = pct > 80 ? 'bg-red-500' : pct > 60 ? 'bg-yellow-500' : 'bg-blue-500'
  const sevColor = anomaly.severity === 'critical'
    ? 'text-red-700 dark:text-red-400'
    : 'text-yellow-700 dark:text-yellow-400'
  const sevBg = anomaly.severity === 'critical'
    ? 'bg-red-100 dark:bg-red-500/10'
    : 'bg-yellow-100 dark:bg-yellow-500/10'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={onClose}>
      <div className="absolute inset-0 bg-black/40 dark:bg-black/60" />
      <div
        className="relative bg-card dark:bg-purple-800 border border-border dark:border-purple-700 rounded-xl p-5 max-w-lg w-full mx-4 max-h-[85vh] overflow-y-auto"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <TrendingUp size={18} className={sevColor} />
            <span className={`text-xs font-bold uppercase px-2 py-0.5 rounded ${sevBg} ${sevColor}`}>
              {anomaly.severity} anomaly
            </span>
          </div>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-800 dark:text-purple-300 dark:hover:text-white transition-colors">
            <X size={18} />
          </button>
        </div>

        {/* Metric name */}
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">{anomaly.metric}</h3>

        {/* Z-score + confidence */}
        <div className="space-y-3 mb-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="rounded-lg p-3 bg-surface dark:bg-purple-900/50 border border-border dark:border-purple-700">
              <span className="text-xs text-gray-500 dark:text-purple-300">Z-Score</span>
              <p className={`text-2xl font-bold mt-1 ${sevColor}`}>
                {typeof anomaly.z_score === 'number' ? anomaly.z_score.toFixed(2) : anomaly.z_score}
              </p>
              <p className="text-xs text-gray-500 dark:text-purple-300 mt-1">Standard deviations from mean</p>
            </div>
            <div className="rounded-lg p-3 bg-surface dark:bg-purple-900/50 border border-border dark:border-purple-700">
              <span className="text-xs text-gray-500 dark:text-purple-300">Confidence</span>
              <div className="flex items-end gap-2 mt-1">
                <p className={`text-2xl font-bold ${sevColor}`}>{pct}%</p>
              </div>
              <div className="w-full h-1.5 bg-gray-200 dark:bg-purple-700 rounded-full mt-2">
                <div className={`h-full ${barColor} rounded-full`} style={{ width: `${pct}%` }} />
              </div>
            </div>
          </div>

          {/* Current vs baseline */}
          <div className="rounded-lg p-3 bg-surface dark:bg-purple-900/50 border border-border dark:border-purple-700">
            <div className="flex items-center justify-between text-sm mb-2">
              <span className="text-gray-500 dark:text-purple-300">Current value</span>
              <span className={`font-bold ${sevColor}`}>
                {typeof anomaly.value === 'number' ? anomaly.value.toFixed(2) : anomaly.value}
              </span>
            </div>
            <div className="flex items-center justify-between text-sm mb-2">
              <span className="text-gray-500 dark:text-purple-300">Baseline mean</span>
              <span className="text-gray-700 dark:text-purple-100">
                {typeof anomaly.baseline_mean === 'number' ? anomaly.baseline_mean.toFixed(2) : anomaly.baseline_mean}
              </span>
            </div>
            {anomaly.baseline_stddev != null && (
              <div className="flex items-center justify-between text-sm">
                <span className="text-gray-500 dark:text-purple-300">Baseline stddev</span>
                <span className="text-gray-700 dark:text-purple-100">
                  {typeof anomaly.baseline_stddev === 'number' ? anomaly.baseline_stddev.toFixed(2) : anomaly.baseline_stddev}
                </span>
              </div>
            )}
          </div>

          {/* Explanations */}
          <div className="rounded-lg p-3 bg-surface dark:bg-purple-900/50 border border-border dark:border-purple-700 space-y-2">
            <div>
              <span className="text-xs font-semibold text-gray-500 dark:text-purple-300 uppercase">Confidence Explanation</span>
              <p className="text-sm text-gray-700 dark:text-purple-100 mt-0.5">{confidenceExplanation(anomaly.confidence)}</p>
            </div>
            <div>
              <span className="text-xs font-semibold text-gray-500 dark:text-purple-300 uppercase">Severity</span>
              <p className="text-sm text-gray-700 dark:text-purple-100 mt-0.5">{severityExplanation(anomaly.severity, anomaly.confidence)}</p>
            </div>
          </div>

          {/* Timestamp */}
          {anomaly.timestamp && (
            <p className="text-xs text-gray-500 dark:text-purple-300">
              Detected: {new Date(anomaly.timestamp).toLocaleString()}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
