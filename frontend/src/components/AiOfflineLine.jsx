// File: frontend/src/components/AiOfflineLine.jsx
// Purpose: REQ-GHA-042 clauses 2-3 — the one line said wherever AI is offline; its number opens the alert

import { offlineWhen } from '../utils/systems'

export default function AiOfflineLine({ offline, onOpenAlert }) {
  return (
    <span className="text-sm font-medium text-gray-700 dark:text-purple-100">
      AI evaluation offline since {offlineWhen(offline)}. See alert{' '}
      <button type="button" className="underline text-accent-600 dark:text-accent-300"
        onClick={e => { e.stopPropagation(); onOpenAlert?.(offline) }}>{offline.alert}</button>{' '}
      for details.
    </span>
  )
}
