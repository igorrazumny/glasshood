// File: frontend/src/components/AiOfflineLine.jsx
// Purpose: REQ-GHA-042 clauses 2-3 — the one line said wherever AI is offline; its number opens the alert

import { offlineLine, offlineWhen } from '../utils/systems'

// compact: one line that keeps the alert number in reach however narrow the space (REQ-GHA-047)
export default function AiOfflineLine({ offline, onOpenAlert, compact = false }) {
  if (compact) {
    return (
      <span className="flex items-center gap-1 min-w-0 max-w-full text-sm font-medium text-gray-700 dark:text-purple-100" title={offlineLine(offline)}>
        <span className="truncate">AI evaluation offline since {offlineWhen(offline)}.</span>
        <button type="button" className="shrink-0 underline text-accent-600 dark:text-accent-300"
          onClick={e => { e.stopPropagation(); onOpenAlert?.(offline) }}>See alert {offline.alert}</button>
      </span>
    )
  }
  return (
    <span className="text-sm font-medium text-gray-700 dark:text-purple-100">
      AI evaluation offline since {offlineWhen(offline)}. See alert{' '}
      <button type="button" className="underline text-accent-600 dark:text-accent-300"
        onClick={e => { e.stopPropagation(); onOpenAlert?.(offline) }}>{offline.alert}</button>{' '}
      for details.
    </span>
  )
}
