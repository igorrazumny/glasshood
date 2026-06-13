// File: frontend/src/components/ErrorBoundary.jsx
// Purpose: Catch rendering crashes, display error, send crash report to backend

import { Component } from 'react'

// Send crash report to backend for Cloud Logging visibility
function reportCrash(error, errorInfo) {
  try {
    const report = {
      error: error?.toString(),
      message: error?.message,
      stack: error?.stack?.split('\n').slice(0, 10).join('\n'),
      componentStack: errorInfo?.componentStack?.split('\n').slice(0, 10).join('\n'),
      url: window.location.href,
      timestamp: new Date().toISOString(),
      uptime_ms: performance.now(),
    }
    // Fire and forget — don't let reporting failure cause another crash
    fetch('/api/frontend-error', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(report),
    }).catch(() => {})
    console.error('[GlassHood] Crash report sent:', report)
  } catch {
    // Reporting itself failed — just log
    console.error('[GlassHood] Failed to send crash report')
  }
}

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null, errorInfo: null }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  componentDidCatch(error, errorInfo) {
    this.setState({ errorInfo })
    reportCrash(error, errorInfo)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen bg-surface dark:bg-purple-950 flex items-center justify-center p-8">
          <div className="bg-card dark:bg-purple-800 border border-red-500/30 rounded-xl p-6 max-w-2xl w-full">
            <h1 className="text-red-400 text-lg font-semibold mb-2">Rendering Error</h1>
            <p className="text-gray-400 text-sm mb-4">
              The dashboard crashed during rendering. This is a bug — please report the error below.
            </p>
            <div className="bg-black/50 rounded-lg p-4 mb-4 overflow-auto max-h-48">
              <pre className="text-red-300 text-xs whitespace-pre-wrap">
                {this.state.error?.toString()}
              </pre>
              {this.state.errorInfo && (
                <pre className="text-gray-500 text-xs mt-2 whitespace-pre-wrap">
                  {this.state.errorInfo.componentStack}
                </pre>
              )}
            </div>
            <div className="text-gray-600 text-xs mb-4">
              Uptime: {Math.round(performance.now() / 1000)}s — crash report sent to server
            </div>
            <button
              onClick={() => window.location.reload()}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm rounded-lg"
            >
              Reload Page
            </button>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}
