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
