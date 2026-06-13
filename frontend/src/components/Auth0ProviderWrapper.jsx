// File: frontend/src/components/Auth0ProviderWrapper.jsx
// Purpose: Auth0 provider wrapper (ported from ColdVault)

import { Auth0Provider } from '@auth0/auth0-react'
import auth0Config from '../config/auth0'

export default function Auth0ProviderWrapper({ children }) {
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
