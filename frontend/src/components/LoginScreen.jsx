// File: frontend/src/components/LoginScreen.jsx
// Purpose: Login gate — demo mode (no creds) + live mode (email/password/SSO)

import { useState, useEffect } from 'react'
import { useAuth0 } from '@auth0/auth0-react'
import { Eye, EyeOff } from 'lucide-react'
import { login } from '../utils/api'

// Brand colors
const CV_BLUE = '#5BD3F4'
const GH_ORANGE = '#E87040'

export default function LoginScreen({ onLogin, onDemo, prefillDemo, setPrefillDemo }) {
  const { loginWithRedirect } = useAuth0()
  const [loginEmail, setLoginEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [showPassword, setShowPassword] = useState(false)

  const handleLogin = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await login(loginEmail, password)
      onLogin()
    } catch {
      setError('Invalid credentials')
    } finally {
      setLoading(false)
    }
  }

  const handleEnterDemo = () => {
    onDemo()
  }

  const handleSwitchToLive = () => {
    setPrefillDemo(false)
    setLoginEmail('')
    setPassword('')
    setError('')
    window.history.replaceState(null, '', '/')
  }

  const handleExploreDemo = () => {
    setPrefillDemo(true)
    setError('')
    window.history.replaceState(null, '', '/?demo')
  }

  // === DEMO MODE: just "Enter Demo" button, no credentials ===
  if (prefillDemo) {
    return (
      <div className="min-h-screen bg-surface dark:bg-purple-950 flex items-center justify-center">
        <div className="bg-card dark:bg-purple-800 border border-border dark:border-purple-700 rounded-lg p-8 w-96 text-center">
          <div className="flex flex-col items-center mb-6">
            <img src="/glasshood-logo-full.png" alt="GlassHood" className="h-20 mb-1" />
            <a href="https://9robots.ai" target="_blank" rel="noopener noreferrer"
              className="text-xs mt-1 hover:opacity-80 transition-opacity" style={{ color: CV_BLUE }}>
              by 9Robots
            </a>
          </div>
          <button
            onClick={handleEnterDemo}
            className="w-full text-white rounded py-3 font-medium text-lg transition-opacity hover:opacity-90"
            style={{ background: `linear-gradient(135deg, ${GH_ORANGE}, ${CV_BLUE})` }}
          >
            Enter Demo
          </button>
          <div className="mt-4">
            <button type="button" onClick={handleSwitchToLive}
              className="hover:opacity-80 text-xs" style={{ color: CV_BLUE }}>
              Login to live system
            </button>
          </div>
          <p className="text-gray-600 text-xs mt-3">AI Infrastructure Audit</p>
        </div>
      </div>
    )
  }

  // === LIVE MODE: email/password + SSO ===
  return (
    <div className="min-h-screen bg-surface dark:bg-purple-950 flex items-center justify-center">
      <form onSubmit={handleLogin} className="bg-card dark:bg-purple-800 border border-border dark:border-purple-700 rounded-lg p-8 w-96">
        <div className="flex flex-col items-center mb-6">
          <img src="/glasshood-logo-full.png" alt="GlassHood" className="h-20 mb-1" />
          <a href="https://9robots.ai" target="_blank" rel="noopener noreferrer"
            className="text-xs mt-1 hover:opacity-80 transition-opacity" style={{ color: CV_BLUE }}>
            by 9Robots
          </a>
        </div>
        <input
          type="email"
          placeholder="Email"
          value={loginEmail}
          onChange={(e) => setLoginEmail(e.target.value)}
          className="w-full bg-surface dark:bg-purple-900 border border-border dark:border-purple-700 rounded px-3 py-2 text-white placeholder-gray-500 mb-3 focus:outline-none"
          onFocus={e => e.target.style.borderColor = CV_BLUE}
          onBlur={e => e.target.style.borderColor = ''}
          autoFocus
        />
        <div className="relative mb-4">
          <input
            type={showPassword ? 'text' : 'password'}
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full bg-surface dark:bg-purple-900 border border-border dark:border-purple-700 rounded px-3 py-2 pr-10 text-white placeholder-gray-500 focus:outline-none"
            onFocus={e => e.target.style.borderColor = CV_BLUE}
            onBlur={e => e.target.style.borderColor = ''}
          />
          <button
            type="button"
            onClick={() => setShowPassword(v => !v)}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300 transition-colors"
            aria-label={showPassword ? 'Hide password' : 'Show password'}
          >
            {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
          </button>
        </div>
        {error && <p className="text-red-400 text-sm mb-3">{error}</p>}
        <button
          type="submit"
          disabled={loading}
          className="w-full text-white rounded py-2 font-medium disabled:opacity-50 transition-opacity"
          style={{ background: `linear-gradient(135deg, ${GH_ORANGE}, ${CV_BLUE})` }}
        >
          {loading ? 'Authenticating...' : 'Login'}
        </button>
        <div className="flex items-center gap-2 my-4">
          <div className="flex-1 border-t border-border dark:border-purple-700" />
          <span className="text-gray-500 text-xs">or</span>
          <div className="flex-1 border-t border-border dark:border-purple-700" />
        </div>
        <button
          type="button"
          onClick={() => loginWithRedirect()}
          className="w-full bg-surface dark:bg-purple-900 border border-border dark:border-purple-700 text-gray-300 rounded py-2 text-sm font-medium hover:border-gray-500 transition-colors flex items-center justify-center gap-2"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <path d="M15.68 8.18c0-.567-.05-1.113-.145-1.636H8v3.094h4.305a3.68 3.68 0 0 1-1.597 2.415v2.007h2.585c1.513-1.393 2.387-3.444 2.387-5.88Z" fill="#4285F4"/>
            <path d="M8 16c2.16 0 3.97-.716 5.293-1.94l-2.585-2.008c-.716.48-1.633.763-2.708.763-2.083 0-3.846-1.407-4.476-3.298H.862v2.073A7.997 7.997 0 0 0 8 16Z" fill="#34A853"/>
            <path d="M3.524 9.517A4.81 4.81 0 0 1 3.273 8c0-.526.09-1.037.25-1.517V4.41H.863A7.997 7.997 0 0 0 0 8c0 1.29.31 2.512.862 3.59l2.662-2.073Z" fill="#FBBC05"/>
            <path d="M8 3.185c1.174 0 2.229.404 3.058 1.196l2.294-2.294C11.966.792 10.156 0 8 0A7.997 7.997 0 0 0 .862 4.41l2.662 2.073C4.154 4.592 5.917 3.185 8 3.185Z" fill="#EA4335"/>
          </svg>
          Sign in with Corporate SSO
        </button>
        <div className="mt-4 text-center">
          <button type="button" onClick={handleExploreDemo} className="text-gray-400 hover:text-gray-300 text-xs">
            Explore demo
          </button>
        </div>
        <p className="text-gray-600 text-xs mt-3 text-center">AI Infrastructure Audit</p>
      </form>
    </div>
  )
}
