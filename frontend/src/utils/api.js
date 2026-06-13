// File: frontend/src/utils/api.js
// Purpose: API fetch wrapper with Auth0 + legacy token + auto-reauth on 401

let _token = sessionStorage.getItem('glasshood_token') || null
let _auth0GetToken = null  // Auth0 getAccessTokenSilently function

export function setToken(token) {
  _token = token
  sessionStorage.setItem('glasshood_token', token)
}

export function clearToken() {
  _token = null
  sessionStorage.removeItem('glasshood_token')
  sessionStorage.removeItem('glasshood_creds')
}

export function getToken() {
  return _token
}

export function setAuth0TokenGetter(fn) {
  _auth0GetToken = fn
}

function _storeCreds(loginEmail, password, role) {
  sessionStorage.setItem('glasshood_creds', JSON.stringify({ login: loginEmail, password, role: role || 'viewer' }))
}

export function getUserRole() {
  try {
    const raw = sessionStorage.getItem('glasshood_creds')
    return raw ? JSON.parse(raw).role || 'viewer' : 'viewer'
  } catch { return 'viewer' }
}

async function _reauth() {
  const raw = sessionStorage.getItem('glasshood_creds')
  if (!raw) return false
  try {
    const { login: loginEmail, password } = JSON.parse(raw)
    const resp = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ login: loginEmail, password }),
    })
    if (!resp.ok) return false
    const data = await resp.json()
    setToken(data.token)
    return true
  } catch {
    return false
  }
}

async function _getAuthHeader() {
  // Auth0 token takes priority
  if (_auth0GetToken) {
    try {
      const token = await _auth0GetToken()
      if (token) return `Bearer ${token}`
    } catch {
      // Auth0 token fetch failed — fall through to legacy
    }
  }
  // Legacy token
  if (_token) return `Bearer ${_token}`
  return null
}

export async function apiFetch(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...options.headers }
  const authHeader = await _getAuthHeader()
  if (authHeader) {
    headers['Authorization'] = authHeader
  }

  let resp = await fetch(path, { ...options, headers })

  // Auto-reauth on 401
  if (resp.status === 401) {
    if (_auth0GetToken) {
      // Auth0: try silent token refresh, then retry once
      try {
        const freshToken = await _auth0GetToken({ cacheMode: 'off' })
        if (freshToken) {
          headers['Authorization'] = `Bearer ${freshToken}`
          resp = await fetch(path, { ...options, headers })
        }
      } catch {
        // Silent refresh failed — session expired
      }
      if (resp.status === 401) {
        clearToken()
        _auth0GetToken = null
        throw new Error('Unauthorized')
      }
    } else {
      // Legacy: try stored credentials
      const ok = await _reauth()
      if (ok) {
        headers['Authorization'] = `Bearer ${_token}`
        resp = await fetch(path, { ...options, headers })
      }
      if (resp.status === 401) {
        clearToken()
        throw new Error('Unauthorized')
      }
    }
  }

  if (!resp.ok) {
    const text = await resp.text()
    throw new Error(`${resp.status}: ${text}`)
  }

  return resp.json()
}

export async function login(loginEmail, password) {
  const resp = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ login: loginEmail, password }),
  })

  if (!resp.ok) {
    throw new Error('Invalid password')
  }

  const data = await resp.json()
  setToken(data.token)
  _storeCreds(loginEmail, password, data.role)
  return data
}
