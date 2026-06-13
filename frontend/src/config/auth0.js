// File: frontend/src/config/auth0.js
// Purpose: Auth0 configuration for GlassHood (same tenant as ColdVault)

const auth0Config = {
  domain: 'your-tenant.us.auth0.com',
  clientId: 'YOUR_AUTH0_CLIENT_ID',
  audience: 'https://api.9robots.ai',
  redirectUri: window.location.origin,
  scope: 'openid profile email',
  cacheLocation: 'localstorage',
  useRefreshTokens: true,
  useRefreshTokensFallback: true,
}

export default auth0Config
