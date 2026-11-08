// File: frontend/src/components/PanelSplit.jsx
// Purpose: REQ-GHA-046 clause 14: drag or arrow keys move the boundary between review and alerts.
import { clampSplit } from '../utils/panelSplit'

export default function PanelSplit({ value, containerRef, onChange, onDone }) {
  const fromPointer = e => {
    const r = containerRef.current?.getBoundingClientRect()
    return r && r.height ? clampSplit((e.clientY - r.top) / r.height) : value
  }
  const down = e => {
    e.preventDefault()
    let last = value
    const move = ev => { last = fromPointer(ev); onChange(last) }
    const up = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      onDone(last)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }
  const key = e => {
    const step = { ArrowUp: -0.05, ArrowDown: 0.05 }[e.key]
    if (!step) return
    e.preventDefault()
    const next = clampSplit(value + step)
    onChange(next); onDone(next)
  }
  return (
    <div role="separator" aria-orientation="horizontal" aria-label="Boundary between AI review and alerts"
      aria-valuenow={Math.round(value * 100)} aria-valuemin={15} aria-valuemax={85} tabIndex={0}
      onPointerDown={down} onKeyDown={key} title="Drag to give the AI review or the alerts more room"
      className="flex-shrink-0 h-2 my-0.5 cursor-row-resize rounded bg-border/60 hover:bg-accent-500/60 focus:bg-accent-500/60 dark:bg-purple-700/60 touch-none" />
  )
}
