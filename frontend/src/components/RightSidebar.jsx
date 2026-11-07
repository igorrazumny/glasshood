// File: frontend/src/components/RightSidebar.jsx
// Purpose: Right sidebar — fixed position, mirrors ProjectTree structure for symmetry
// REQ-GHA-033: clearly visible hide/show controls, a draggable inner edge, and the
// content laid out as a column so the alarm list can take the height that is left.

import { useRef, useEffect, useState } from 'react'
import { Pin, PinOff, PanelLeftClose, PanelLeft } from 'lucide-react'
import PanelEdge from './PanelEdge'
import { PANEL_TOP } from '../utils/panels'

export default function RightSidebar({ open, pinned, onToggle, onPin, width, onResize, children }) {
  const ref = useRef(null)
  const [resizing, setResizing] = useState(false)

  // Click outside closes unpinned panel
  useEffect(() => {
    if (!open || pinned) return
    const handler = (e) => {
      if (ref.current && !ref.current.contains(e.target)) {
        onToggle()
      }
    }
    document.addEventListener('pointerdown', handler)
    return () => document.removeEventListener('pointerdown', handler)
  }, [open, pinned, onToggle])

  return (
    <>
      {/* Hover trigger zone when hidden */}
      {!open && (
        <div
          className="fixed right-0 w-4 z-40"
          style={{ top: PANEL_TOP, bottom: 0 }}
          onMouseEnter={onToggle}
        />
      )}

      {/* REQ-009: toggle tab + panel chrome get dark: variants — ColdVault
          purple-800/700 surfaces, purple-200/100 hover-text on dark. */}
      {!open && (
        <button
          onClick={onToggle}
          className="fixed right-0 z-50 w-7 py-3 bg-card dark:bg-purple-800 border-y border-l border-border dark:border-purple-700 rounded-l-lg shadow flex flex-col items-center gap-2 text-gray-600 hover:text-gray-900 dark:text-purple-200 dark:hover:text-white transition-colors"
          style={{ top: PANEL_TOP + 12 }}
          title="Show the AI overview and alarms"
        >
          <PanelLeft size={16} className="rotate-180" />
          <span className="text-xs font-medium [writing-mode:vertical-rl]">Overview &amp; alarms</span>
        </button>
      )}

      {/* Panel */}
      <div
        ref={ref}
        className={`fixed right-0 z-40 bg-card dark:bg-purple-900 border-l border-border dark:border-purple-700 flex flex-col overflow-hidden rounded-l-lg ${
          resizing ? '' : 'transition-all duration-300'
        }`}
        style={{ top: PANEL_TOP, bottom: 0, width: open ? width : 0 }}
      >
        {open && <PanelEdge side="right" onResize={onResize} onResizing={setResizing} />}
        {/* Pin + hide controls — mirrors ProjectTree exactly */}
        <div className="flex items-center justify-end px-2 py-1.5 flex-shrink-0">
          <div className="flex items-center gap-1.5">
            <button
              onClick={onPin}
              className="text-gray-500 hover:text-gray-800 dark:text-purple-300 dark:hover:text-purple-100 transition-colors"
              title={pinned ? 'Unpin panel' : 'Pin panel'}
            >
              {pinned ? <Pin size={12} /> : <PinOff size={12} className="opacity-40 hover:opacity-100" />}
            </button>
            <button
              onClick={onToggle}
              className="flex items-center gap-1 px-1.5 py-0.5 rounded border border-border dark:border-purple-700 text-xs text-gray-600 hover:text-gray-900 hover:bg-surface dark:text-purple-200 dark:hover:text-white dark:hover:bg-purple-800 transition-colors"
              title="Hide the AI overview and alarms"
            >
              <PanelLeftClose size={14} className="rotate-180" />
              Hide
            </button>
          </div>
        </div>

        {/* Scrollable content */}
        <div className="flex-1 min-h-0 overflow-y-auto p-2 pt-0 flex flex-col" style={{ width }}>
          {children}
        </div>
      </div>
    </>
  )
}
