// File: frontend/src/utils/systems.js
// Purpose: REQ-GHA-035 — several monitored systems side by side. Each landscape file is one
// system; a box belongs to the system its landscape file (or its parent box) names.

import { worstStatus } from './canvasParts.js'
import { alarmLevel } from './alarms.js'
import { clock, dateTime } from './time.js'

const NOT_READ = new Set(['not checked', 'not monitored', 'unknown', 'stale'])

// REQ-GHA-035 clause 9: systems monitored from inside vs public systems seen from outside
export const GROUPS = [
  { id: 'group-internal', label: 'Proprietary systems', outside: false },
  { id: 'group-external', label: 'External systems', outside: true },
]
// REQ-GHA-037: left edges in the projects tree, so All systems -> group -> system step equally
export const TREE_LEFT = { groupChevron: 22, system: 60 }

// REQ-GHA-037: the designers' own logos, for our own systems only
// REQ-GHA-045 clause 2: the domain each of our own systems is reached at
const DOMAINS = { glasshood: 'glasshood.ai', coldvault: 'coldvault.ai', testrobin: 'testrobin.ai' }
const LOGOS = { glasshood: '/glasshood-logo-full.png', coldvault: '/logos/coldvault.png', testrobin: '/logos/testrobin.png' }

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
    const outside = m.kind === 'outside_view'
    cards.push({
      id, product: m.product, label: m.solution || m.display_name || m.product || 'System',
      subtitle: DOMAINS[m.product] || (m.display_name && m.display_name !== m.solution ? m.display_name : ''),
      source: outside && m.source ? String(m.source).replace(/^https?:\/\//, '').replace(/\/$/, '') : '',
      sourceUrl: outside && /^https?:\/\//.test(String(m.source || '')) ? String(m.source) : null,
      notes,
      outside,
      logo: outside ? null : LOGOS[m.product] || null,
      state: worstStatus(statuses.filter(s => s && !NOT_READ.has(s) && s !== 'idle')) || 'not checked',
      line: plainLine(statuses, outside),
      parts: mine.length,
      critical: open.filter(a => a.severity === 'critical').length,
      warning: open.filter(a => a.severity === 'warning').length,
    })
  }
  return cards
}

// REQ-GHA-040: what a summary says about a system comes only from its saved record: condition,
// mark, alert counts and written time were saved together and cannot disagree with the AI text
const FROM_CONDITION = { normal: 'healthy', attention: 'degraded', failing: 'error' }
const OWN_WORDS = { normal: 'Running normally', attention: 'Running, with something that needs attention', failing: 'Not working properly' }
const PROVIDER_WORDS = { normal: 'Running normally, as reported by the provider', attention: 'The provider reports problems', failing: 'The provider reports outages' }

// REQ-GHA-042: when AI went offline, in the reader's zone
export function offlineWhen(offline) {
  const at = new Date(offline.since)
  return at.toDateString() === new Date().toDateString() ? clock(at.getTime()) : dateTime(at.getTime())
}

export function offlineLine(offline) {
  return `AI evaluation offline since ${offlineWhen(offline)}. See alert ${offline.alert} for details.`
}

export function withRecords(cards, records) {
  return (cards || []).map(c => {
    const record = records?.[c.product]
    if (record?.ai_offline) {
      return { ...c, offline: record.ai_offline, notice: null, state: 'not checked', critical: 0, warning: 0, notes: 0,
        line: offlineLine(record.ai_offline) }
    }
    const notice = record?.critical_notice || null   // REQ-GHA-041 clause 7: no AI call behind it
    if (!record?.condition) {
      return { ...c, notice, state: 'not checked', critical: 0, warning: 0, notes: 0,
        line: records ? 'Not assessed yet' : 'Status not available yet' }
    }
    const alerts = record.alerts || []
    const open = alerts.filter(a => alarmLevel(a) !== 'info')
    return { ...c, notice, state: FROM_CONDITION[record.condition],
      line: (c.outside ? PROVIDER_WORDS : OWN_WORDS)[record.condition],
      critical: open.filter(a => a.severity === 'critical').length,
      warning: open.filter(a => a.severity === 'warning').length,
      notes: alerts.length - open.length }
  })
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

// REQ-GHA-037 with REQ-GHA-024 clause 7 (amended 2026-11-08): an assessment says when it was
// written and keeps the last real text whatever its age; what is happening now is said apart
export function assessmentLine(about, nowMs) {
  if (!about) return { when: null, text: 'AI evaluation has not started yet.', problem: null, busy: false, job: null }
  const at = about.analyzed_at ? about.analyzed_at * 1000 : null
  const sameDay = at && new Date(at).toDateString() === new Date(nowMs).toDateString()
  // REQ-GHA-030: every time carries its zone
  const when = at ? (sameDay ? `evaluated ${clock(at)}` : `evaluated ${dateTime(at)}`) : null
  const problem = about.error ? `Latest update failed: ${about.error}` : null
  const state = about.job?.status
  const tries = about.job?.attempts
  const busy = state === 'running' || state === 'retrying'
  const pending = state === 'running' ? 'AI evaluation in progress.'
    : state === 'retrying' ? 'The AI evaluation failed; another attempt is scheduled.'
      : state === 'failed' ? (tries > 1 ? `The AI evaluation failed after ${tries} attempts.` : 'The AI evaluation failed.')
        : 'AI evaluation has not started yet.'
  // beside a kept text, the job's state is its own line
  const job = !about.summary ? null : state === 'running' ? 'A new AI evaluation is in progress.'
    : state === 'retrying' ? 'Another attempt at updating this is scheduled.'
      : state === 'failed' ? 'It will be tried again at the next scheduled round.' : null
  return { when, text: about.summary || pending, problem, busy, job }
}

// REQ-GHA-037 clause 6: a read that failed is said in plain words, never shown as loading
export function loadFailed(what, error) {
  return `${what} could not be loaded (${String(error).replace(/^\d{3}:\s*/, '').slice(0, 120)}); trying again.`
}

// REQ-GHA-037 clause 6: a refresh that failed while older data stays on screen
export function staleDataLine(error, lastUpdatedMs) {
  if (!error || !lastUpdatedMs) return null
  return `Could not refresh (${String(error).replace(/^\d{3}:\s*/, '').slice(0, 120)}); showing the data from ${clock(lastUpdatedMs)}. Trying again.`
}

// REQ-GHA-037 clause 9 with REQ-GHA-024: the list of per-system assessments on the home view
// or a group says, for each system, when it was written, whether it is old and whether the
// latest update failed, exactly as that system's card does
export function listAssessments(cards, descriptions, nowMs, loadError = null) {
  return (cards || []).map(c => {
    const about = descriptions?.[c.product] || null
    const line = assessmentLine(about, nowMs)
    if (about?.ai_offline) return { id: c.id, label: c.label, waiting: false, offline: about.ai_offline, last: about.summary ? line : null, job: null, problem: null, when: null, text: '' }
    if (!about && loadError) return { id: c.id, label: c.label, waiting: false, ...line, text: loadFailed('The assessment', loadError) }
    if (loadError) return { id: c.id, label: c.label, waiting: false, ...line, problem: line.problem || loadFailed('A newer assessment', loadError) }
    return { id: c.id, label: c.label, waiting: line.busy && !line.job, ...line }
  })
}

// REQ-GHA-037 clause 7: the header says what it covers — per group on the home view,
// the selected system's own state when one is chosen

export function headerLine(cards, activeProject) {
  const off = cards.find(c => c.offline)
  if (off) return { text: off.line, state: 'unknown', offline: off.offline }
  const one = cards.find(c => c.id === activeProject)
  if (one) return { text: `${one.label}: ${statusWord(one.state)}`, state: one.state }
  const groups = groupedCards(cardsInGroup(cards, isGroupId(activeProject) ? activeProject : null))
  if (!groups.length) return { text: 'Loading your systems…', state: 'unknown' }
  const parts = groups.map(({ group, cards: gc }) => {
    const name = group.outside ? 'External services' : 'Our systems'
    if (gc.every(c => c.state === 'not checked')) return `${name}: status not available`
    const n = gc.filter(c => c.state === 'error' || c.state === 'degraded' || c.critical).length
    const u = gc.filter(c => c.state === 'not checked' && !c.critical).length
    // a system not yet assessed is named, never folded into "operating normally"
    if (!u) return `${name}: ${n ? `${n} need${n === 1 ? 's' : ''} attention` : 'operating normally'}`
    const ok = gc.length - n - u
    const bits = [n && `${n} need${n === 1 ? 's' : ''} attention`, ok && `${ok} operating normally`, `${u} status unavailable`]
    return `${name}: ${bits.filter(Boolean).join(', ')}`
  })
  // red only for our own systems; an external service's trouble alone shows amber
  const own = groups.filter(g => !g.group.outside).flatMap(g => g.cards)
  const ext = groups.filter(g => g.group.outside).flatMap(g => g.cards)
  const state = own.some(c => c.state === 'error') ? 'error'
    : own.some(c => c.state === 'degraded' || c.critical) || ext.some(c => c.state === 'error' || c.state === 'degraded' || c.critical) ? 'degraded'
    : [...own, ...ext].every(c => c.state === 'healthy') ? 'healthy' : 'unknown'
  return { text: parts.join(' · '), state }
}

// REQ-GHA-045 clause 5: one word per state, wherever a system's status is summarised, and the reason first
const STATUS_WORD = { healthy: 'Healthy', degraded: 'Needs attention', error: 'Degraded' }
export function statusWord(state) { return STATUS_WORD[state] || 'Unknown' }

export function statusReason(card) {
  const n = (card.critical || 0) + (card.warning || 0)
  if (n) return `${n} alert${n === 1 ? '' : 's'}${card.critical ? ` (${card.critical} critical)` : ''}`
  if (card.notes) return `${card.notes} configuration note${card.notes === 1 ? '' : 's'}`
  return ''
}

// REQ-GHA-045 clause 4: what the last monitoring cycle changed, from the existing comparison
export function changeLines(diff, max = 5) {
  if (!diff || diff.first_run) return { none: 'Nothing to compare yet', lines: [], more: 0 }
  const name = c => c.after?.label || c.before?.label || c.id
  const all = [
    ...(diff.changed || []).map(c => (c.before?.status !== c.after?.status
      ? `${name(c)}: ${c.before?.status} to ${c.after?.status}` : `${name(c)}: details changed`)),
    ...(diff.added || []).map(id => `${id}: new`),
    ...(diff.removed || []).map(id => `${id}: removed`),
  ]
  return { none: all.length ? null : 'No changes', lines: all.slice(0, max), more: Math.max(0, all.length - max), unassigned: diff.unassigned || 0 }
}

// REQ-GHA-037 clause 7 applies to the changes too: a group's panel lists only that group's parts.
// A removed part no longer belongs to any system, so it is counted apart, never attributed.
export function scopeDiff(diff, owner, cardIds) {
  if (!diff || diff.first_run) return diff
  const inScope = id => cardIds.has(owner.get(id))
  const removed = diff.removed || []
  return { ...diff, added: (diff.added || []).filter(inScope), changed: (diff.changed || []).filter(c => inScope(c.id)),
    removed: removed.filter(inScope), unassigned: removed.filter(id => !owner.has(id)).length }
}
