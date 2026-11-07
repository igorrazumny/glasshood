// File: frontend/src/components/PanelEdge.jsx
// Purpose: REQ-GHA-033 — the draggable inner edge of a side panel.
// Drag it to make the panel wider or narrower; double-click puts back the default width.

import { useCallback } from 'react'
import { dragWidth, PANELS } from '../utils/panels'

export default function PanelEdge({ side, onResize, onResizing }) {
  const start = useCallback((e) => {
    e.preventDefault()
    onResizing?.(true)
    const move = ev => onResize(dragWidth(side, ev.clientX, window.innerWidth))
    const end = () => {
      onResizing?.(false)
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', end)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', end)
  }, [side, onResize, onResizing])

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      title="Drag to resize · double-click for the default width"
      onPointerDown={start}
      onDoubleClick={() => onResize(PANELS[side].width)}
      className={`absolute top-0 bottom-0 ${side === 'left' ? 'right-0' : 'left-0'} w-1.5 cursor-col-resize z-10
        hover:bg-blue-400/40 active:bg-blue-500/50 dark:hover:bg-purple-400/40 transition-colors`}
    />
  )
}
