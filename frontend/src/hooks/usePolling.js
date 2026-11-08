// File: frontend/src/hooks/usePolling.js
// Purpose: Poll API endpoints with backoff on error

import { useState, useEffect, useRef, useCallback } from 'react'
import { apiFetch } from '../utils/api'
import { sessionEpoch, stored as storedAnswer, store } from '../utils/pollCache.js'

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
    const ep = sessionEpoch()
    // an answer is used only by the same mounted view, for the same path, in the same session
    const current = () => generation.current === gen && currentPath.current === path && sessionEpoch() === ep
    try {
      const result = await apiFetch(path)
      const at = Date.now()
      // a late answer is never stored either: it could be older than one already kept
      if (!current() || !store(path, result, at, ep)) return
      setData(result)
      setError(null)
      setLastUpdated(at)
      failCount.current = 0
    } catch (e) {
      if (!current()) return
      failCount.current++
      setError(e.message)
    }
  }, [path])

  useEffect(() => {
    generation.current++
    currentPath.current = path
    // this path's own last answer at once (never another path's), then a fresh read
    const stored = path ? storedAnswer(path) : null
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
    // an unmounted or switched view takes no late answer
    return () => { alive = false; generation.current++; clearTimeout(timerRef.current) }
  }, [poll, intervalMs, path])

  return { data, error, lastUpdated, refresh: poll }
}
