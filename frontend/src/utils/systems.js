// File: frontend/src/utils/systems.js
// Purpose: REQ-GHA-035 — several monitored systems side by side. Each landscape file is one
// system; a box belongs to the system its landscape file (or its parent box) names.

import { worstStatus } from './canvasParts.js'
import { alarmLevel } from './alarms.js'
import { clock, dateTime } from './time.js'

const NOT_READ = new Set(['not checked', 'not monitored', 'unknown', 'stale'])

// REQ-GHA-035 clause 9: systems monitored from inside vs public systems seen from outside
export const GROUPS = [
  { id: 'group-internal', label: '9Robots systems', outside: false },
  { id: 'group-external', label: 'External systems', outside: true },
]
export const isGroupId = id => GROUPS.some(g => g.id === id)

// The cards of one group (or all cards when no group is given)
export function cardsInGroup(cards, groupId) {
  const g = GROUPS.find(x => x.id === groupId)
  return g ? cards.filter(c => c.outside === g.outside) : cards
}

// [{group, cards}] for the groups that have systems, in display order
export function groupedCards(cards) {
  return GROUPS.map(group => ({ group, cards: cardsInGroup(cards, group.id) })).filter(x => x.cards.length)
}

export const systemId = m => `manifest-${m?.product || 'unknown'}-${m?.environment || 'unknown'}`

// Every box including the ones drawn inside another (container, app, embeddings)
export function allBoxes(nodes) {
  const out = []
  const walk = list => { for (const n of list || []) { if (n?.id) { out.push(n); walk(n.children) } } }
  walk(nodes)
  return out
}

// node id -> system id, from the boxes' project/env tags (set by the backend); a box inside
// another box belongs to the same system as the box it is in
export function systemOfNodes(nodes, manifests) {
  const byKey = new Map((manifests || []).map(m => [`${m.product}|${m.environment}`, systemId(m)]))
  const out = new Map()
  const walk = (list, inherited) => {
    for (const n of list || []) {
      if (!n?.id) continue
      const id = byKey.get(`${n.project}|${n.env}`) || inherited
      if (id) out.set(n.id, id)
      walk(n.children, id)
    }
  }
  walk(nodes, undefined)
  return out
}

// REQ-GHA-037: the state in words a business owner uses; counts of unchecked parts stay in the system view
function plainLine(statuses, outside) {
  const read = statuses.filter(s => s && !NOT_READ.has(s) && s !== 'idle')
  if (!statuses.length) return 'No parts reported yet'
  if (!read.length) return 'Not checked yet'
  const count = s => read.filter(x => x === s).length
  const parts = n => `${n} part${n === 1 ? '' : 's'}`
  const worst = worstStatus(read)
  if (outside) {
    if (worst === 'error') return `The provider reports outages in ${parts(count('error'))}`
    if (worst === 'degraded') return `The provider reports problems in ${parts(count('degraded'))}`
    return 'Running normally, as reported by the provider'
  }
  if (worst === 'error') return `Not working properly: ${parts(count('error'))} failing`
  if (worst === 'degraded') return `Running, with problems in ${parts(count('degraded'))}`
  return 'Running normally'
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
    const mine = allBoxes(nodes).filter(n => owner.get(n.id) === id)
    const statuses = mine.map(n => n.status)
    // REQ-GHA-037 clause 8: alerts to review apart from configuration notes; examples not counted
    const mineAll = (alerts || []).filter(a => owner.get(a.node_id) === id && a.kind !== 'example')
    // the same levels as the alarm lists (REQ-GHA-038): Information is a note, the rest are alerts
    const open = mineAll.filter(a => alarmLevel(a) !== 'info')
    const notes = mineAll.filter(a => alarmLevel(a) === 'info').length
    const polls = mine.map(n => n.metrics?._last_poll).filter(Number.isFinite)
    const outside = m.kind === 'outside_view'
    cards.push({
      id, product: m.product, label: m.solution || m.display_name || m.product || 'System',
      subtitle: m.display_name && m.display_name !== m.solution ? m.display_name : '',
      source: outside && m.source ? `Source: ${String(m.source).replace(/^https?:\/\//, '').replace(/\/$/, '')}` : '',
      notes,
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

// REQ-GHA-037 with REQ-GHA-024 clause 7: an AI assessment says when it was written, says
// plainly when it is old or its latest refresh failed, and keeps the last good text as old
export function assessmentLine(about, nowMs, maxAgeS = 3 * 3600) {
  if (!about) return { when: null, text: 'Being written; it appears within a few minutes.', old: null, problem: null }
  const at = about.analyzed_at ? about.analyzed_at * 1000 : null
  const ageS = at ? (nowMs - at) / 1000 : null
  const sameDay = at && new Date(at).toDateString() === new Date(nowMs).toDateString()
  // REQ-GHA-030: every time carries its zone
  const when = at ? (sameDay ? `written ${clock(at)}` : `written ${dateTime(at)}`) : null
  const hours = ageS ? Math.round(ageS / 3600) : 0
  const old = at && (about.stale || ageS > maxAgeS)
    ? `This assessment is ${hours >= 1 ? `${hours} h` : `${Math.round(ageS / 60)} min`} old; the system may have changed since.` : null
  const problem = about.error ? `Latest update failed: ${about.error}` : null
  const text = about.summary || (about.error ? 'No assessment yet.' : 'Being written; it appears within a few minutes.')
  return { when, text, old, problem }
}

// REQ-GHA-037 clause 7: the header says what it covers — per group on the home view,
// the selected system's own state when one is chosen
const SYSTEM_WORDS = { healthy: 'operating normally', degraded: 'needs attention', error: 'not working properly',
  'not checked': 'status not available' }

export function headerLine(cards, activeProject) {
  const one = cards.find(c => c.id === activeProject)
  if (one) return { text: `${one.label}: ${SYSTEM_WORDS[one.state] || 'status not available'}`, state: one.state }
  const groups = groupedCards(cardsInGroup(cards, isGroupId(activeProject) ? activeProject : null))
  if (!groups.length) return { text: 'Loading your systems…', state: 'unknown' }
  const parts = groups.map(({ group, cards: gc }) => {
    const name = group.outside ? 'External services' : 'Our systems'
    if (gc.every(c => c.state === 'not checked')) return `${name}: status not available`
    const n = gc.filter(c => c.state === 'error' || c.state === 'degraded' || c.critical).length
    return `${name}: ${n ? `${n} need${n === 1 ? 's' : ''} attention` : 'operating normally'}`
  })
  // red only for our own systems; an external service's trouble alone shows amber
  const own = groups.filter(g => !g.group.outside).flatMap(g => g.cards)
  const ext = groups.filter(g => g.group.outside).flatMap(g => g.cards)
  const state = own.some(c => c.state === 'error') ? 'error'
    : own.some(c => c.state === 'degraded' || c.critical) || ext.some(c => c.state === 'error' || c.state === 'degraded' || c.critical) ? 'degraded'
    : [...own, ...ext].every(c => c.state === 'healthy') ? 'healthy' : 'unknown'
  return { text: parts.join(' · '), state }
}
