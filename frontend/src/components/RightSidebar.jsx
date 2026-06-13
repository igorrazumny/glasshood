// File: frontend/src/components/RightSidebar.jsx
// Purpose: Right sidebar — fixed position, mirrors ProjectTree structure for symmetry

import { useRef, useEffect } from 'react'
import { Pin, PinOff, PanelLeftClose, PanelLeft } from 'lucide-react'

export default function RightSidebar({ open, pinned, onToggle, onPin, children }) {
  const ref = useRef(null)

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
          style={{ top: '40px', bottom: 0 }}
          onMouseEnter={onToggle}
        />
      )}

      {/* REQ-009: toggle tab + panel chrome get dark: variants — ColdVault
          purple-800/700 surfaces, purple-200/100 hover-text on dark. */}
      {!open && (
        <button
          onClick={onToggle}
          className="fixed right-0 z-50 w-5 h-10 bg-card dark:bg-purple-800 border-y border-l border-border dark:border-purple-700 rounded-l flex items-center justify-center text-gray-500 hover:text-gray-800 dark:text-purple-300 dark:hover:text-purple-100 transition-colors"
          style={{ top: '52px' }}
          title="Show panel"
        >
          <PanelLeft size={12} className="rotate-180" />
        </button>
      )}

      {/* Panel */}
      <div
        ref={ref}
        className={`fixed right-0 z-40 bg-card dark:bg-purple-900 border-l border-border dark:border-purple-700 flex flex-col transition-all duration-300 overflow-hidden rounded-l-lg ${
          open ? 'w-80' : 'w-0'
        }`}
        style={{ top: '40px', bottom: 0 }}
      >
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
              className="text-gray-500 hover:text-gray-800 dark:text-purple-300 dark:hover:text-purple-100 transition-colors"
              title="Hide panel"
            >
              <PanelLeftClose size={14} className="rotate-180" />
            </button>
          </div>
        </div>

        {/* Scrollable content */}
        <div className="flex-1 overflow-y-auto p-2 pt-0 w-80">
          {children}
        </div>
      </div>
    </>
  )
}
