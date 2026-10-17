// File: frontend/src/components/Auth0ProviderWrapper.jsx
// Purpose: Auth0 provider wrapper (ported from ColdVault)

import { Auth0Provider, useAuth0 } from '@auth0/auth0-react'
import auth0Config from '../config/auth0'

// Session state when Auth0 is switched off (REQ-GHA-017): never loading, never
// authenticated, and no Auth0 functions to call.
const AUTH0_OFF = {
  enabled: false,
  isAuthenticated: false,
  isLoading: false,
  user: undefined,
  getAccessTokenSilently: null,
  loginWithRedirect: null,
  logout: null,
}

// Use this instead of useAuth0(). auth0Config.enabled is fixed at build time,
// so the hook call order is the same on every render.
export function useAuthSession() {
  if (!auth0Config.enabled) return AUTH0_OFF
  return { enabled: true, ...useAuth0() }
}

export default function Auth0ProviderWrapper({ children }) {
  if (!auth0Config.enabled) return children

  const onRedirectCallback = (appState) => {
    window.location.replace(appState?.returnTo || window.location.pathname)
  }

  return (
    <Auth0Provider
      domain={auth0Config.domain}
      clientId={auth0Config.clientId}
      authorizationParams={{
        redirect_uri: auth0Config.redirectUri,
        audience: auth0Config.audience,
        scope: auth0Config.scope,
      }}
      onRedirectCallback={onRedirectCallback}
      cacheLocation={auth0Config.cacheLocation}
      useRefreshTokens={auth0Config.useRefreshTokens}
      useRefreshTokensFallback={auth0Config.useRefreshTokensFallback}
    >
      {children}
    </Auth0Provider>
  )
}
