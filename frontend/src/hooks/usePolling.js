// File: frontend/src/hooks/usePolling.js
// Purpose: Poll API endpoints with backoff on error

import { useState, useEffect, useRef, useCallback } from 'react'
import { apiFetch, pollCache } from '../utils/api'

export function usePolling(path, intervalMs = 15000) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [lastUpdated, setLastUpdated] = useState(null)
  const failCount = useRef(0)
  const timerRef = useRef(null)

  // REQ-GHA-036: when the path changes (another system selected), an answer for the old
  // path that arrives late is dropped, and the old data is not shown as the new one's
  const currentPath = useRef(path)
  // Each switch starts a new generation; an answer to a read started before the latest switch
  // is dropped, also when the user came back to the same path in between (A -> B -> A)
  const generation = useRef(0)

  const poll = useCallback(async () => {
    if (!path) return
    const gen = generation.current
    try {
      const result = await apiFetch(path)
      if (generation.current !== gen || currentPath.current !== path) return
      const at = Date.now()
      pollCache.set(path, { data: result, at })
      setData(result)
      setError(null)
      setLastUpdated(at)
      failCount.current = 0
    } catch (e) {
      if (generation.current !== gen || currentPath.current !== path) return
      failCount.current++
      setError(e.message)
    }
  }, [path])

  useEffect(() => {
    generation.current++
    currentPath.current = path
    // this path's own last answer at once (never another path's), then a fresh read
    const stored = path ? pollCache.get(path) : null
    setData(stored ? stored.data : null)
    setLastUpdated(stored ? stored.at : null)
    setError(null)   // an error from the previous path is not this one's
    if (!path) return
    let alive = true
    poll() // Initial fetch

    const schedule = () => {
      const backoff = Math.min(failCount.current * 5000, 30000)
      const delay = intervalMs + backoff
      timerRef.current = setTimeout(async () => {
        await poll()
        if (alive) schedule()
      }, delay)
    }

    schedule()
    return () => { alive = false; clearTimeout(timerRef.current) }
  }, [poll, intervalMs, path])

  return { data, error, lastUpdated, refresh: poll }
}
