// File: frontend/src/config/auth0Flag.js
// Purpose: REQ-GHA-017 — Auth0 is parked. It is on only when the build sets
// VITE_AUTH0_ENABLED=true (plus a real domain and client id in auth0.js);
// otherwise the app never starts the Auth0 client and the login screen shows
// no SSO option. Kept free of browser globals so it can be tested under node.

export function isAuth0Enabled(env) {
  return env?.VITE_AUTH0_ENABLED === 'true'
}
