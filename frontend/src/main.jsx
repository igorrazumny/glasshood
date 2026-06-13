import React from 'react'
import ReactDOM from 'react-dom/client'
import Auth0ProviderWrapper from './components/Auth0ProviderWrapper'
import { ThemeProvider } from './hooks/useTheme'
import App from './App'
import './index.css'

// REQ-009: ThemeProvider wraps the app so any descendant can call useTheme()
// to read the current theme or update the preference. Sits inside Auth0 so
// the theme survives login/logout transitions.
ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <Auth0ProviderWrapper>
      <ThemeProvider>
        <App />
      </ThemeProvider>
    </Auth0ProviderWrapper>
  </React.StrictMode>
)
