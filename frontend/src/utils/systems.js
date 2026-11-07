// File: frontend/src/utils/systems.js
// Purpose: REQ-GHA-035 — several monitored systems side by side. Each landscape file is one
// system; a box belongs to the system its landscape file (or its parent box) names.

import { worstStatus } from './canvasParts.js'

const NOT_READ = new Set(['not checked', 'not monitored', 'unknown', 'stale'])

export const systemId = m => `manifest-${m?.product || 'unknown'}-${m?.environment || 'unknown'}`

// node id -> system id, from the boxes' project/env tags (set by the backend)
export function systemOfNodes(nodes, manifests) {
  const byKey = new Map((manifests || []).map(m => [`${m.product}|${m.environment}`, systemId(m)]))
  const out = new Map()
  for (const n of nodes || []) {
    const id = byKey.get(`${n.project}|${n.env}`)
    if (id) out.set(n.id, id)
  }
  return out
}

function plainLine(statuses, outside) {
  const read = statuses.filter(s => s && !NOT_READ.has(s) && s !== 'idle')
  if (!statuses.length) return 'No parts reported yet'
  if (!read.length) return 'Not checked yet: no part could be read'
  const count = s => read.filter(x => x === s).length
  const worst = worstStatus(read)
  const unread = statuses.length - read.length - statuses.filter(s => s === 'idle').length
  const tail = unread > 0 ? ` · ${unread} not checked` : ''
  const who = outside ? 'reported by the provider' : 'checked'
  if (worst === 'error') return `${count('error')} part${count('error') === 1 ? '' : 's'} failing, ${who}${tail}`
  if (worst === 'degraded') return `${count('degraded')} part${count('degraded') === 1 ? '' : 's'} with problems, ${who}${tail}`
  return `All ${read.length} ${outside ? 'reported' : 'checked'} parts working${tail}`
}

// One card per system: name, outside view or ours, state, one plain line, open alarms, last check
export function systemCards(manifests, nodes, alerts) {
  const owner = systemOfNodes(nodes, manifests)
  const seen = new Set()
  const cards = []
  for (const m of manifests || []) {
    const id = systemId(m)
    if (seen.has(id)) continue
    seen.add(id)
    const mine = (nodes || []).filter(n => owner.get(n.id) === id)
    const statuses = mine.map(n => n.status)
    const open = (alerts || []).filter(a => owner.get(a.node_id) === id)
    const polls = mine.map(n => n.metrics?._last_poll).filter(Number.isFinite)
    const outside = m.kind === 'outside_view'
    cards.push({
      id, label: m.solution || m.display_name || m.product || 'System',
      subtitle: m.display_name && m.display_name !== m.solution ? m.display_name : '',
      outside,
      state: worstStatus(statuses.filter(s => s && !NOT_READ.has(s) && s !== 'idle')) || 'not checked',
      line: plainLine(statuses, outside),
      parts: mine.length,
      critical: open.filter(a => a.severity === 'critical').length,
      warning: open.filter(a => a.severity === 'warning').length,
      checkedAt: polls.length ? Math.max(...polls) : null,
    })
  }
  return cards
}

// The portfolio line above the cards
export function portfolioLine(cards) {
  const attention = cards.filter(c => c.state === 'error' || c.state === 'degraded' || c.critical).length
  const unread = cards.filter(c => c.state === 'not checked').length
  const parts = [`${cards.length} system${cards.length === 1 ? '' : 's'}`]
  parts.push(attention ? `${attention} need${attention === 1 ? 's' : ''} attention` : 'none needs attention')
  if (unread) parts.push(`${unread} not checked`)
  return parts.join(' · ')
}
