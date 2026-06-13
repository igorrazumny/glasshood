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

  const poll = useCallback(async () => {
    if (!path) return
    try {
      const result = await apiFetch(path)
      setData(result)
      setError(null)
      setLastUpdated(Date.now())
      failCount.current = 0
    } catch (e) {
      failCount.current++
      setError(e.message)
    }
  }, [path])

  useEffect(() => {
    if (!path) return
    poll() // Initial fetch

    const schedule = () => {
      const backoff = Math.min(failCount.current * 5000, 30000)
      const delay = intervalMs + backoff
      timerRef.current = setTimeout(async () => {
        await poll()
        schedule()
      }, delay)
    }

    schedule()
    return () => clearTimeout(timerRef.current)
  }, [poll, intervalMs])

  return { data, error, lastUpdated, refresh: poll }
}
