// File: frontend/src/App.jsx
// Purpose: Root component — Auth0 + legacy login gate + dashboard, ?demo for demo mode

import { useState, useEffect } from 'react'
import { useAuth0 } from '@auth0/auth0-react'
import LoginScreen from './components/LoginScreen'
import Dashboard from './components/Dashboard'
import ErrorBoundary from './components/ErrorBoundary'
import { getToken, clearToken, setAuth0TokenGetter } from './utils/api'

function getInitialState() {
  const params = new URLSearchParams(window.location.search)
  // Canonical guest entry is the clean path /demo (a "Live demo" — a showcase
  // instance, not public read-only exposure of every tenant). The backend SPA
  // catch-all serves index.html for /demo. Accept legacy ?demo + ?view + /view
  // too, and normalize the address bar to the clean /demo (no query string).
  const pathGuest = window.location.pathname.startsWith('/demo') ||
                    window.location.pathname.startsWith('/view')
  const hasGuest = params.has('demo') || params.has('view') || pathGuest
  if (hasGuest) {
    window.history.replaceState(null, '', '/demo')
  }
  if (getToken()) return { mode: 'live', prefillDemo: false }
  return { mode: 'login', prefillDemo: hasGuest }
}

export default function App() {
  const initial = getInitialState()
  const [mode, setMode] = useState(initial.mode)
  const [prefillDemo, setPrefillDemo] = useState(initial.prefillDemo)
  const { isAuthenticated, isLoading, user, getAccessTokenSilently, logout: auth0Logout } = useAuth0()

  // When Auth0 authenticates, switch to live mode and wire up token getter
  useEffect(() => {
    if (isAuthenticated && mode !== 'demo') {
      setAuth0TokenGetter(getAccessTokenSilently)
      setMode('live')
    }
  }, [isAuthenticated])

  const handleLogin = () => setMode('live')

  const handleDemo = async () => {
    // Demo = live view, no masking (REQ-214). Silent login with demo creds.
    try {
      const { login: loginFn } = await import('./utils/api.js')
      await loginFn('demo@glasshood.example.com', 'demo')
      setMode('live')
    } catch {
      // Fallback to old static demo if login fails
      setMode('demo')
    }
  }

  const handleLogout = () => {
    clearToken()
    setAuth0TokenGetter(null)
    if (isAuthenticated) {
      auth0Logout({ logoutParams: { returnTo: window.location.origin } })
    } else {
      setMode('login')
      setPrefillDemo(false)
    }
  }

  const handleSwitchToLive = () => {
    setMode('login')
    setPrefillDemo(false)
  }

  // Show nothing while Auth0 is loading (prevents flash of login)
  if (isLoading) {
    return (
      <div className="min-h-screen bg-surface dark:bg-purple-950 flex items-center justify-center">
        <div className="text-gray-500 dark:text-purple-300 text-sm">Loading...</div>
      </div>
    )
  }

  if (mode === 'demo') {
    return <ErrorBoundary><Dashboard mode="demo" onSwitchToLive={handleSwitchToLive} /></ErrorBoundary>
  }

  if (mode === 'live') {
    return <ErrorBoundary><Dashboard mode="live" onLogout={handleLogout} /></ErrorBoundary>
  }

  return (
    <ErrorBoundary>
      <LoginScreen
        onLogin={handleLogin}
        onDemo={handleDemo}
        prefillDemo={prefillDemo}
        setPrefillDemo={setPrefillDemo}
      />
    </ErrorBoundary>
  )
}
