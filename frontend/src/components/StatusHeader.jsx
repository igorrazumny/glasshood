// File: frontend/src/components/StatusHeader.jsx
// Purpose: Top bar — overall status, last updated, refresh button, theme toggle.

import { useState, useEffect, useRef } from 'react'
import { RefreshCw, LogOut, ShieldCheck, Monitor, Sun, Moon } from 'lucide-react'
import { useTheme } from '../hooks/useTheme'

const STATUS_TEXT = {
  healthy: 'All Systems Operational',
  degraded: 'Degraded Performance',
  error: 'System Issues Detected',
  unknown: 'Checking...',
}

// REQ-009: status text + dot get dark-mode variants. Light keeps the existing
// REQ-005/006/008 hexes; dark uses ColdVault's purple-300/100 light-blue
// derivatives that read clearly on purple-950.
const STATUS_COLOR = {
  healthy: 'text-green-600 dark:text-green-400',
  degraded: 'text-yellow-600 dark:text-yellow-400',
  error: 'text-red-600 dark:text-red-400',
  unknown: 'text-gray-500 dark:text-purple-200',
}

const STATUS_DOT = {
  healthy: 'bg-green-500',
  degraded: 'bg-yellow-500',
  error: 'bg-red-500',
  unknown: 'bg-gray-400 dark:bg-purple-400',
}

// REQ-009: 3-button segmented theme toggle (Auto / Light / Dark) — niobe's
// recommended pattern. Sits in the header top-right next to refresh + logout.
// Active button uses ColdVault's brand accent (purple-300/#5BD3F4).
// A11y: WAI-ARIA radiogroup with arrow-key + Home/End navigation per
// authoring practices (9r round-3 fix).
// 9r round-5 fix: queueMicrotask isn't on the older Safari / WebView
// versions we already worked around in useTheme via addListener. Use it
// when available, fall back to setTimeout(0) otherwise.
const deferFocus = (cb) => {
  if (typeof queueMicrotask === 'function') queueMicrotask(cb)
  else setTimeout(cb, 0)
}

function ThemeToggle() {
  const { themePreference, setThemePreference } = useTheme()
  const options = [
    { value: 'auto',  label: 'Auto',  Icon: Monitor },
    { value: 'light', label: 'Light', Icon: Sun },
    { value: 'dark',  label: 'Dark',  Icon: Moon },
  ]
  // 9r round-4 fix: refs so arrow-key selection can move DOM focus too.
  const buttonRefs = useRef([])
  // 9r round-5 fix: prefRef tracks the latest preference so the keydown
  // handler doesn't see a stale closure during keyboard auto-repeat (a
  // burst of arrow events arriving between React renders would all read
  // the same `currentIdx` from render time without this).
  const prefRef = useRef(themePreference)
  useEffect(() => { prefRef.current = themePreference }, [themePreference])

  const select = (nextIdx) => {
    const value = options[nextIdx].value
    setThemePreference(value)
    prefRef.current = value  // keep the ref in sync this tick too
    // Focus follows selection per WAI-ARIA radiogroup pattern.
    deferFocus(() => buttonRefs.current[nextIdx]?.focus())
  }

  const handleKeyDown = (e) => {
    // Read latest preference via ref so auto-repeat sees fresh state.
    const liveIdx = Math.max(0, options.findIndex(o => o.value === prefRef.current))
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
      e.preventDefault()
      select((liveIdx + 1) % options.length)
    } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
      e.preventDefault()
      select((liveIdx - 1 + options.length) % options.length)
    } else if (e.key === 'Home') {
      e.preventDefault()
      select(0)
    } else if (e.key === 'End') {
      e.preventDefault()
      select(options.length - 1)
    }
  }

  return (
    <div
      className="flex items-center rounded-md border border-border dark:border-purple-700 bg-card dark:bg-purple-800/40 p-0.5"
      role="radiogroup"
      aria-label="Theme"
      onKeyDown={handleKeyDown}
    >
      {options.map(({ value, label, Icon }, idx) => {
        const active = themePreference === value
        return (
          <button
            key={value}
            ref={el => { buttonRefs.current[idx] = el }}
            type="button"
            role="radio"
            aria-checked={active}
            // Roving tabindex: only the active option is in the tab sequence;
            // arrow keys move within the group.
            tabIndex={active ? 0 : -1}
            // 9r round-7 fix: also route clicks through select() so DOM focus
            // moves to the clicked button — otherwise focus stays on the
            // previously-active radio and subsequent arrow keys fire against
            // a stale focused element until the browser reconciles.
            onClick={() => select(idx)}
            title={`Theme: ${label}`}
            className={
              'flex items-center justify-center w-6 h-6 rounded transition-colors ' +
              (active
                ? 'bg-accent-500/20 text-accent-600 dark:bg-accent-500/20 dark:text-accent-300'
                : 'text-gray-500 hover:text-gray-700 dark:text-purple-200 dark:hover:text-purple-100')
            }
          >
            <Icon size={12} />
          </button>
        )
      })}
    </div>
  )
}

export default function StatusHeader({ topology, lastUpdated, onRefresh, onLogout, isDemo, onVerify }) {
  const [ago, setAgo] = useState(0)
  const [refreshing, setRefreshing] = useState(false)
  const [version, setVersion] = useState('')

  useEffect(() => {
    fetch('/api/version')
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d?.version) setVersion(d.version) })
      .catch(() => {})
  }, [])

  useEffect(() => {
    const timer = setInterval(() => {
      if (lastUpdated) setAgo(Math.round((Date.now() - lastUpdated) / 1000))
    }, 1000)
    return () => clearInterval(timer)
  }, [lastUpdated])

  const status = topology?.overall_status || 'unknown'
  // REQ-009: ago indicator gets dark-mode variants for the "stale" colors.
  const agoColor =
    ago > 60 ? 'text-red-600 dark:text-red-400'
    : ago > 30 ? 'text-yellow-600 dark:text-yellow-400'
    : 'text-gray-500 dark:text-purple-200'

  const handleRefresh = async () => {
    setRefreshing(true)
    await onRefresh()
    setRefreshing(false)
  }

  return (
    <div className="flex items-center justify-between px-2 sm:px-4 h-10 bg-card dark:bg-purple-900 border-b border-border dark:border-purple-700 relative z-50 transition-colors duration-200">
      <div className="flex items-center gap-2 sm:gap-3 min-w-0">
        <img src="/glasshood-logo-full.png" alt="GlassHood" className="h-6 sm:h-7 flex-shrink-0" />
        {version && <span className="text-[10px] text-gray-500 dark:text-purple-300 hidden sm:inline">v{version}</span>}
        {isDemo && <span className="text-xs bg-accent-500/20 text-accent-700 dark:bg-accent-500/20 dark:text-accent-300 px-1.5 py-0.5 rounded">DEMO</span>}
        <div className={`w-2 h-2 rounded-full flex-shrink-0 ${STATUS_DOT[status]} animate-pulse`} title={STATUS_TEXT[status]} />
        <span className={`text-sm font-medium truncate hidden sm:inline ${STATUS_COLOR[status]}`}>
          {STATUS_TEXT[status]}
        </span>
      </div>

      <div className="flex items-center gap-2 sm:gap-3 flex-shrink-0">
        <span className={`text-xs sm:text-sm ${agoColor}`}>
          {lastUpdated ? `${ago}s` : '...'}
        </span>
        {onVerify && (
          <button
            onClick={onVerify}
            className="text-gray-500 hover:text-blue-600 dark:text-purple-200 dark:hover:text-accent-300 transition-colors"
            title="Verify Manifests"
          >
            <ShieldCheck size={14} />
          </button>
        )}
        <button
          onClick={handleRefresh}
          className="text-gray-500 hover:text-gray-800 dark:text-purple-200 dark:hover:text-purple-100 transition-colors"
          title="Refresh"
        >
          <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
        </button>
        <ThemeToggle />
        {onLogout && (
          <button
            onClick={onLogout}
            className="text-gray-500 hover:text-gray-700 dark:text-purple-300 dark:hover:text-purple-100 transition-colors"
            title="Logout"
          >
            <LogOut size={14} />
          </button>
        )}
      </div>
    </div>
  )
}
