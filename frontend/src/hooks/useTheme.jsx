// File: frontend/src/hooks/useTheme.jsx
// Purpose: REQ-009 theme switcher — React Context + two-piece state.
//
// Two pieces of state (niobe's reference doc §1, adopted verbatim):
//   themePreference: 'auto' | 'dark' | 'light' — what the user picked.
//   theme:           'dark' | 'light'           — the applied theme, always concrete.
//
// 'auto' is a preference, not a renderable value. Components need a concrete
// dark/light string, so the toggle UI renders the chosen preference (including
// "Auto") while the rest of the app only ever sees 'dark' or 'light'.
//
// Persistence: localStorage key `glasshood-theme-preference` stores the
// PREFERENCE string. Storing the preference (not the derived theme) means a
// user who picked Auto keeps following the OS the next time they open the app,
// not whatever the OS happened to be at write time.
//
// FOUC: the matching <script> in index.html applies the `.dark`/`.light` class
// to <html> BEFORE React mounts, so first paint matches the user's preference.
// This hook keeps it in sync after mount.
//
// Context shape (the public API of this module):
//   { themePreference, theme, setThemePreference(value), toggleTheme() }
// NOTE: there is NO exported `setTheme`. The internal `setTheme` useState
// setter is private — `theme` is derived from `themePreference` and should
// not be set directly. To change the applied theme, call `setThemePreference`
// or `toggleTheme`.

import { createContext, useContext, useEffect, useState } from 'react'

const STORAGE_KEY = 'glasshood-theme-preference'

function readInitialPreference() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored === 'dark' || stored === 'light' || stored === 'auto') return stored
  } catch {}
  return 'auto'
}

function resolveAutoTheme() {
  if (typeof window !== 'undefined' && window.matchMedia) {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  }
  return 'light'  // SSR / no matchMedia: default to light (GlassHood default)
}

const ThemeContext = createContext({
  themePreference: 'auto',
  theme: 'light',
  setThemePreference: () => {},
  toggleTheme: () => {},
})

export function ThemeProvider({ children }) {
  const [themePreference, setThemePreference] = useState(readInitialPreference)
  const [theme, setTheme] = useState(() => {
    const pref = readInitialPreference()
    return pref === 'auto' ? resolveAutoTheme() : pref
  })

  // Persist preference + sync concrete theme when preference changes.
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, themePreference)
    } catch {}
    if (themePreference === 'dark' || themePreference === 'light') {
      setTheme(themePreference)
    } else {
      setTheme(resolveAutoTheme())
    }
  }, [themePreference])

  // Subscribe to OS theme changes while in auto mode (niobe §2).
  // 9r round-2 fix: older Safari / WebView versions support `addListener`
  // (legacy MediaQueryList API) but not `addEventListener`. Use whichever
  // is present so the hook doesn't crash on legacy browsers when 'auto'
  // is active. Detach with the matching remover.
  useEffect(() => {
    if (themePreference !== 'auto') return
    if (typeof window === 'undefined' || !window.matchMedia) return
    const mql = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = (e) => setTheme(e.matches ? 'dark' : 'light')
    if (typeof mql.addEventListener === 'function') {
      mql.addEventListener('change', onChange)
      return () => mql.removeEventListener('change', onChange)
    }
    if (typeof mql.addListener === 'function') {
      mql.addListener(onChange)
      return () => mql.removeListener(onChange)
    }
  }, [themePreference])

  // Apply the `.dark` / `.light` class to <html> so Tailwind `dark:` variants
  // resolve and the CSS-var blocks in index.css (`:root` vs `.dark`) switch.
  // The FOUC script set this on first paint; this keeps it in sync.
  useEffect(() => {
    const root = document.documentElement
    if (theme === 'dark') {
      root.classList.add('dark')
      root.classList.remove('light')
    } else {
      root.classList.add('light')
      root.classList.remove('dark')
    }
  }, [theme])

  // Convenience toggle — Auto cycles to the OPPOSITE of the currently
  // applied theme (i.e. acts as "give me the other one"). Light/Dark
  // flip to each other directly.
  const toggleTheme = () => {
    if (themePreference === 'auto') {
      setThemePreference(theme === 'dark' ? 'light' : 'dark')
    } else {
      setThemePreference(themePreference === 'dark' ? 'light' : 'dark')
    }
  }

  return (
    <ThemeContext.Provider value={{ themePreference, theme, setThemePreference, toggleTheme }}>
      {children}
    </ThemeContext.Provider>
  )
}

export function useTheme() {
  return useContext(ThemeContext)
}
