// File: frontend/src/hooks/usePolling.js
// Purpose: Poll API endpoints with backoff on error

import { useState, useEffect, useRef, useCallback } from 'react'
import { apiFetch } from '../utils/api'

export function usePolling(path, intervalMs = 15000) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [lastUpdated, setLastUpdated] = useState(null)
  const failCount = useRef(0)
  const timerRef = useRef(null)

  // REQ-GHA-036: when the path changes (another system selected), an answer for the old
  // path that arrives late is dropped, and the old data is not shown as the new one's
  const currentPath = useRef(path)

  const poll = useCallback(async () => {
    if (!path) return
    try {
      const result = await apiFetch(path)
      if (currentPath.current !== path) return
      setData(result)
      setError(null)
      setLastUpdated(Date.now())
      failCount.current = 0
    } catch (e) {
      if (currentPath.current !== path) return
      failCount.current++
      setError(e.message)
    }
  }, [path])

  useEffect(() => {
    currentPath.current = path
    setData(null)
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
