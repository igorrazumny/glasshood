// File: frontend/src/utils/mcpRecheck.js
// Purpose: REQ-GHA-020 — "Recheck via MCP": which nodes offer it, and how a result reads.

export const PARTNER_NOTE = 'Partner Mode sends the question to outside providers (OpenAI, Google and others).'
export const WAKE_NOTE = 'Sends one short question to ColdVault through its MCP server; this may wake ColdVault.'

// Live demo (viewer) never sees the button; the server refuses it too.
export function canRecheck(node, isDemo) {
  return !isDemo && node?.source === 'manifest' && node?.mcp_recheck === true
}

// One line for the result; the answer text itself is never shown or kept.
export function describeRecheck(result) {
  if (!result) return ''
  const mode = result.mode === 'partner' ? 'Partner Mode' : 'Vault Mode'
  if (result.ok) {
    const by = result.model ? ` by ${result.model}` : ''
    return `Answered${by} in ${result.elapsed_s}s (${mode}).`
  }
  return `No answer (${mode}): ${String(result.reason || 'unknown reason').replace(/\.+$/, '')}.`
}

// apiFetch throws "<status>: <body>"; show the server's detail when it has one.
export function recheckError(err) {
  const msg = String(err?.message || err || '')
  const m = msg.match(/^(\d{3}): (.*)$/s)
  if (!m) return msg || 'Recheck failed'
  try {
    const detail = JSON.parse(m[2]).detail
    if (detail) return String(detail)
  } catch { /* not JSON */ }
  return `Recheck failed (HTTP ${m[1]})`
}
