// File: frontend/src/hooks/useNodePositions.js
// Purpose: Single source of truth for node positions — default + saved + active drag
// Saves to localStorage on drag end. Groups/solutions derive bounds from this.

import { useState, useCallback, useMemo } from 'react'

const STORAGE_KEY = 'glasshood-node-positions'

function loadSaved() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : {}
  } catch { return {} }
}

function saveToDisk(positions) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(positions)) }
  catch (e) { console.warn('Position save failed:', e) }
}

export function useNodePositions(defaultPositions) {
  const [saved, setSaved] = useState(() => loadSaved())
  const [activeDrag, setActiveDrag] = useState(null)

  // Resolved = default, overridden by saved, overridden by active drag
  const positions = useMemo(() => {
    const result = {}
    for (const [id, pos] of Object.entries(defaultPositions || {})) {
      result[id] = saved[id] ?? pos
    }
    if (activeDrag) {
      for (const id of activeDrag.nodeIds) {
        if (activeDrag.current[id]) result[id] = activeDrag.current[id]
      }
    }
    return result
  }, [defaultPositions, saved, activeDrag])

  const startDrag = useCallback((nodeIds, mouseX, mouseY) => {
    const startPos = {}
    for (const id of nodeIds) {
      startPos[id] = positions[id] ?? { x: 0, y: 0 }
    }
    setActiveDrag({
      nodeIds,
      startMouse: { x: mouseX, y: mouseY },
      startPos,
      current: { ...startPos },
    })
  }, [positions])

  const updateDrag = useCallback((mouseX, mouseY) => {
    setActiveDrag(prev => {
      if (!prev) return null
      const dx = mouseX - prev.startMouse.x
      const dy = mouseY - prev.startMouse.y
      const current = {}
      for (const id of prev.nodeIds) {
        current[id] = {
          x: prev.startPos[id].x + dx,
          y: prev.startPos[id].y + dy,
        }
      }
      return { ...prev, current }
    })
  }, [])

  const endDrag = useCallback(() => {
    if (!activeDrag) return
    setSaved(prev => {
      const next = { ...prev }
      for (const id of activeDrag.nodeIds) {
        next[id] = activeDrag.current[id]
      }
      saveToDisk(next)
      return next
    })
    setActiveDrag(null)
  }, [activeDrag])

  const resetPositions = useCallback(() => {
    setSaved({})
    localStorage.removeItem(STORAGE_KEY)
  }, [])

  return { positions, startDrag, updateDrag, endDrag, resetPositions, isDragging: !!activeDrag }
}
