// File: frontend/src/utils/canvasParts.js
// Purpose: REQ-GHA-023 — what the canvas draws, for the dashboard's count and the VM badge.

// REQ-GHA-023 clause 5: the parts drawn on the canvas — placed nodes, everything nested
// inside them, and the parent behind each dynamic group (the MIG drawn as the group box).
// The dashboard's "nodes monitored" counts exactly these.
export function canvasNodes(layout, topologyNodes) {
  if (!layout) return null
  const topo = {}
  for (const n of (topologyNodes || [])) topo[n.id] = n
  const out = []
  const seen = new Set()
  const add = (n) => {
    if (!n?.id || seen.has(n.id)) return
    seen.add(n.id)
    out.push({ id: n.id, status: n.status || 'unknown' })
    for (const c of (n.children || [])) add(c)
  }
  for (const n of (layout.manifestNodes || [])) add(n)
  for (const g of (layout.groups || [])) {
    if (g.parent) add({ id: g.parent, status: topo[g.parent]?.status })
  }
  return out
}

// REQ-GHA-023 clause 3: confidential hardware is a badge on the VM, checked through MCP.
export function attestationBadge(node) {
  const a = node.metrics?.attested
  if (a === undefined || a === null) return ''
  return a ? ' · SEV-SNP attested ✓' : ' · not attested'
}

export function groupCenter(g) {
  return { x: g.x + g.w / 2, y: g.y + g.h / 2 }
}

// REQ-GHA-023 clause 2: where an edge meets a group box — the middle of the side that
// faces the point at the edge's other end. Without that point, the left side (as before).
export function nearestSide(g, p) {
  const c = groupCenter(g)
  const sides = {
    left: { x: g.x, y: c.y }, right: { x: g.x + g.w, y: c.y },
    top: { x: c.x, y: g.y }, bottom: { x: c.x, y: g.y + g.h },
  }
  if (!p) return { side: 'left', point: sides.left }
  const dx = (p.x - c.x) / (g.w / 2 || 1)
  const dy = (p.y - c.y) / (g.h / 2 || 1)
  const side = Math.abs(dx) >= Math.abs(dy) ? (dx < 0 ? 'left' : 'right') : (dy < 0 ? 'top' : 'bottom')
  return { side, point: sides[side] }
}

// REQ-GHA-023 clause 3: with several VMs the attestation cannot be tied to one VM; the
// instance group then carries the endpoint-level result instead.
export function groupAttestationBadge(parentId, topologyNodes) {
  const nodes = topologyNodes || []
  const parent = nodes.find(n => n.id === parentId)
  const a = parent?.metrics?.endpoint_attested
  if (a === undefined || a === null) return ''
  const vms = nodes.filter(n => n.metrics?._parent === parentId).length
  if (vms <= 1) return ''
  return a ? ' · endpoint SEV-SNP attested ✓ (VM not identified)' : ' · endpoint not attested'
}

// REQ-GHA-023 clause 5: the nodes the System Overview counts — the canvas when drawn from
// manifests, else the topology. Nothing until the topology has arrived (manifests may come first).
export function statsNodes(topology, canvas) {
  if (!topology) return null
  const nodes = canvas || topology.nodes
  return nodes?.length ? nodes : null
}

// REQ-GHA-023 clause 3: a dynamic group's colour is the worst of its members and of its
// parent (the instance group), so a failed endpoint attestation turns the group yellow while
// a member's stronger error still wins. Statuses that carry no health are ignored.
// Same ranking the canvas used before (unlisted statuses rank with unknown).
const GROUP_PRIORITY = { healthy: 0, unknown: 1, disabled: 1, degraded: 2, error: 3 }
const NO_HEALTH = new Set(['not monitored', 'not checked'])

export function worstStatus(statuses) {
  let worst = null
  for (const s of statuses) {
    if (!s || NO_HEALTH.has(s)) continue
    if (worst === null || (GROUP_PRIORITY[s] ?? 1) > (GROUP_PRIORITY[worst] ?? 1)) worst = s
  }
  return worst
}

// REQ-GHA-023 clause 9: an edge leaves and enters a box at the side facing the other end,
// so a request runs into the app's left side and out of its right side.
// boxes: id -> {hw, hh} half-sizes; a point with no box (a group side) is used as is.
// horizontal: request/data flow — always the left or right side's middle, by direction.
export function anchorPoint(id, center, other, boxes, horizontal = false) {
  const b = boxes?.[id]
  if (!b || !center || !other) return center
  if (horizontal) return { x: other.x < center.x ? center.x - b.hw : center.x + b.hw, y: center.y }
  return nearestSide({ x: center.x - b.hw, y: center.y - b.hh, w: 2 * b.hw, h: 2 * b.hh }, other).point
}

// Ids of boxes drawn inside another box (container, app, embeddings).
export function nestedChildIds(nodes) {
  const ids = new Set()
  const walk = (children) => { for (const c of children || []) { if (c.id) ids.add(c.id); walk(c.children) } }
  for (const n of nodes || []) walk(n.children)
  return ids
}

// Half-sizes of every drawn box: top-level nodes and the children nested inside them.
export function boxSizes(nodes, { nodeW, nodeHeight, childHeight, childPad }) {
  const boxes = {}
  const walk = (children, hw) => {
    for (const c of children || []) {
      if (c.id) boxes[c.id] = { hw, hh: childHeight(c) / 2 }
      walk(c.children, hw - childPad)
    }
  }
  for (const n of nodes || []) {
    if (!n.id) continue
    boxes[n.id] = { hw: nodeW / 2, hh: nodeHeight(n) / 2 }
    walk(n.children, nodeW / 2 - childPad)
  }
  return boxes
}

// Clause 9 line styles: flow (solid, arrow), thin (configuration, probes, observation), dashed (deployment).
export function edgeStyle(edge) {
  if (edge.style === 'thin') return { width: 0.8, dash: '2 3', arrow: false, showLabel: true, opacity: 0.55 }
  if (edge.style === 'dashed') return { width: 1, dash: '6 4', arrow: true, showLabel: true, opacity: 0.45 }
  return { width: 1.4, dash: 'none', arrow: true, showLabel: false, opacity: 0.6 }
}

// REQ-GHA-023 clause 9: the opening view shows the whole pipeline — a viewBox around all groups.
export function fitViewBox(groups, pad = 60) {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  for (const g of groups || []) {
    minX = Math.min(minX, g.x); minY = Math.min(minY, g.y)
    maxX = Math.max(maxX, g.x + g.w); maxY = Math.max(maxY, g.y + g.h)
  }
  if (minX === Infinity) return null
  return { x: minX - pad, y: minY - pad - 30, w: (maxX - minX) + pad * 2, h: (maxY - minY) + pad * 2 + 30 }
}

// REQ-GHA-023 clause 9: an id starting with "_" in a group's node list is an empty grid cell.
export function isSpacer(id) {
  return typeof id === 'string' && id.startsWith('_')
}

// A connects_to entry: a plain id is request/data flow; {to, style, label} sets the line style.
export function connectionEdge(source, c) {
  const obj = typeof c === 'string' ? { to: c } : (c || {})
  const edge = {
    source,
    target: obj.to,
    label: obj.label || '',
    status: 'healthy',
    style: obj.style || 'default',
  }
  // axis: 'v' leaves the bottom/top middle, 'h' the side middle (clause 9: steer a line
  // around a neighbour, e.g. a branch below the static IP, a step past an attachment).
  if (obj.axis === 'v' || obj.axis === 'h') edge.axis = obj.axis
  return edge
}


// REQ-GHA-023 clause 9: request lines run straight or at right angles. The axis follows the
// larger offset between the boxes (a step below joins bottom-middle to top-middle; a step
// beside joins side middles); a box nested in a VM is always entered and left from the side.
export function flowAnchors(src, tgt, fromC, toC, boxes, nested, prefer) {
  const forceH = nested?.has(src) || nested?.has(tgt)
  const dx = toC.x - fromC.x, dy = toC.y - fromC.y
  const axis = forceH ? 'h' : (prefer || (Math.abs(dx) >= Math.abs(dy) ? 'h' : 'v'))
  const port = (id, c, other) => {
    const b = boxes?.[id]
    if (!b) return c
    if (axis === 'h') return { x: other.x < c.x ? c.x - b.hw : c.x + b.hw, y: c.y }
    return { x: c.x, y: other.y < c.y ? c.y - b.hh : c.y + b.hh }
  }
  return { from: port(src, fromC, toC), to: port(tgt, toC, fromC), axis }
}

// A right-angled path: along the axis to the midpoint, across, then along again.
export function elbowPath(from, to, axis) {
  if (axis === 'h') {
    if (Math.abs(from.y - to.y) < 0.5) return `M ${from.x} ${from.y} L ${to.x} ${to.y}`
    const mx = (from.x + to.x) / 2
    return `M ${from.x} ${from.y} H ${mx} V ${to.y} H ${to.x}`
  }
  if (Math.abs(from.x - to.x) < 0.5) return `M ${from.x} ${from.y} L ${to.x} ${to.y}`
  const my = (from.y + to.y) / 2
  return `M ${from.x} ${from.y} V ${my} H ${to.x} V ${to.y}`
}
