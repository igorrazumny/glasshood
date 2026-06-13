// File: frontend/src/utils/manifestLayout.js
// Purpose: Compute topology layout from static YAML manifests
// Layout algorithm: recursive bottom-up sizing
//   1. Measure nodes within each group → compute group width/height
//   2. Layout groups within environment using row/col → accumulate actual sizes
//   3. Layout environments vertically within product
// No fixed cell sizes — each group sized to fit its actual contents.

// Filter VMs for a dynamic group — only include VMs from THIS group's MIG parent
export function filterVMsForGroup(topologyNodes, groupParent) {
  return (topologyNodes || []).filter(n =>
    n.id?.startsWith('vm-') && n.metrics?._parent === groupParent
  )
}

import { nodeHeight, childHeight, CHILD_H, CHILD_GAP } from '../components/TopologyNode'

const NODE_W = 140    // must match TopologyNode.NODE_W
const NODE_H = 50     // must match TopologyNode.NODE_H
const NODE_GAP_X = 12 // horizontal gap between nodes
const NODE_GAP_Y = 10 // vertical gap between nodes
const GROUP_PAD = 20  // padding inside group boundary
const GROUP_LABEL_H = 25 // space for group label at top
const GROUP_GAP = 30  // gap between groups
const ENV_GAP = 60    // gap between environments (prod/val)
const ENV_LABEL_H = 30 // space for environment label above groups
const ORIGIN_X = 60   // left margin
const ORIGIN_Y = 50   // top margin

// Build a node lookup from manifest nodes[] list
function buildManifestNodeMap(manifest) {
  const map = {}
  for (const node of (manifest.nodes || [])) {
    if (node.id) map[node.id] = node
  }
  return map
}

// Measure a group: compute its width/height based on nodes and their children
function measureGroup(nodeIds, maxCols, nodeMap, topoMap) {
  const cols = Math.min(nodeIds.length, maxCols || 4)
  const rows = Math.ceil(nodeIds.length / cols)
  const w = cols * (NODE_W + NODE_GAP_X) - NODE_GAP_X + GROUP_PAD * 2
  // Use max node height per row (accounts for nested children)
  let totalH = GROUP_LABEL_H + GROUP_PAD * 2
  for (let r = 0; r < rows; r++) {
    let rowMaxH = NODE_H
    for (let c = 0; c < cols; c++) {
      const idx = r * cols + c
      if (idx >= nodeIds.length) break
      const nid = nodeIds[idx]
      const node = topoMap?.[nid] || nodeMap?.[nid] || {}
      const h = nodeHeight(node)
      if (h > rowMaxH) rowMaxH = h
    }
    totalH += rowMaxH + (r > 0 ? NODE_GAP_Y : 0)
  }
  return { w, h: totalH, cols, rows }
}

export function computeManifestLayout(topologyNodes, manifests) {
  if (!Array.isArray(manifests) || manifests.length === 0) return null

  const positions = {}
  const nodeGroups = {}
  const encryptedIds = []
  const groups = []
  const manifestEdges = []
  const manifestNodes = []
  const envLabels = []    // {label, x, y, w} for environment section headers
  // REQ-213: full id→manifest-node map for non-rendered parent lookups (MIG click)
  const manifestNodesById = {}

  // Build lookup from topology nodes (for status enrichment)
  const topoMap = {}
  for (const n of (topologyNodes || [])) topoMap[n.id] = n

  const sortedManifests = [...manifests].sort((a, b) => (a.order || 0) - (b.order || 0))
  let envOffsetY = ORIGIN_Y

  for (const manifest of sortedManifests) {
    const envGroupStart = groups.length  // track which groups belong to this env
    const nodeMap = buildManifestNodeMap(manifest)
    // REQ-213: accumulate ALL manifest nodes (even those not placed in a group)
    // so the click handler can resolve dynamic-group parents like pl-mig.
    for (const mn of (manifest.nodes || [])) {
      if (mn.id) manifestNodesById[mn.id] = mn
    }
    const sortedGroups = [...(manifest.groups || [])].sort((a, b) => (a.order || 0) - (b.order || 0))

    // Auto-assign row/col for groups without explicit placement
    let autoRow = 0
    for (const group of sortedGroups) {
      if (group.row === undefined && group.col === undefined) {
        group.row = autoRow++
        group.col = 0
      }
    }

    // Populate dynamic groups with discovered VMs from topology
    // ONLY include VMs whose _parent matches THIS group's parent node
    for (const group of sortedGroups) {
      if (group.dynamic && group.parent) {
        const discoveredVMs = filterVMsForGroup(topologyNodes, group.parent)
        group.nodes = discoveredVMs.map(n => n.id)
        // VMs inherit parent MIG's log config
        const parentNode = nodeMap[group.parent] || {}
        const parentLogs = parentNode.monitoring?.logs || null
        for (const vm of discoveredVMs) {
          nodeMap[vm.id] = { id: vm.id, label: vm.label, type: 'vm', monitoring: parentNode.monitoring ? { logs: parentLogs } : undefined }
        }
      }
    }

    // Step 1: Measure each group
    const groupMeasures = {}
    for (const group of sortedGroups) {
      const nodeIds = group.nodes || []
      if (nodeIds.length === 0) continue
      const measure = measureGroup(nodeIds, group.columns, nodeMap, topoMap)
      groupMeasures[group.name] = { ...measure, nodeIds, group }
    }

    // Step 2: Build grid — find max row/col
    let maxRow = 0, maxCol = 0
    for (const group of sortedGroups) {
      if (groupMeasures[group.name]) {
        maxRow = Math.max(maxRow, group.row ?? 0)
        maxCol = Math.max(maxCol, group.col ?? 0)
      }
    }

    // Step 3: Compute column widths (max group width in each column)
    const colWidths = {}
    for (const gm of Object.values(groupMeasures)) {
      const c = gm.group.col ?? 0
      colWidths[c] = Math.max(colWidths[c] || 0, gm.w)
    }

    // Step 4: Compute row heights (max group height in each row)
    const rowHeights = {}
    for (const gm of Object.values(groupMeasures)) {
      const r = gm.group.row ?? 0
      rowHeights[r] = Math.max(rowHeights[r] || 0, gm.h)
    }

    // Step 5: Compute cumulative x offsets per column
    const colX = {}
    let cx = ORIGIN_X
    for (let c = 0; c <= maxCol; c++) {
      colX[c] = cx
      cx += (colWidths[c] || 0) + GROUP_GAP
    }

    // Step 6: Compute cumulative y offsets per row (below env label)
    const rowY = {}
    let ry = envOffsetY + ENV_LABEL_H
    for (let r = 0; r <= maxRow; r++) {
      rowY[r] = ry
      ry += (rowHeights[r] || 0) + GROUP_GAP
    }

    // Step 7: Place each group and its nodes
    for (const group of sortedGroups) {
      const gm = groupMeasures[group.name]
      if (!gm) continue

      const groupIdx = groups.length
      const baseX = colX[group.col ?? 0]
      const baseY = rowY[group.row ?? 0]

      // Place nodes inside group (variable height for nested children)
      const rowOffsets = {}  // row index → y offset
      let accY = baseY + GROUP_LABEL_H + GROUP_PAD
      for (let r = 0; r <= Math.floor((gm.nodeIds.length - 1) / gm.cols); r++) {
        rowOffsets[r] = accY
        let rowMaxH = NODE_H
        for (let c = 0; c < gm.cols; c++) {
          const idx = r * gm.cols + c
          if (idx >= gm.nodeIds.length) break
          const nid = gm.nodeIds[idx]
          const node = topoMap[nid] || nodeMap[nid] || {}
          const h = nodeHeight(node)
          if (h > rowMaxH) rowMaxH = h
        }
        accY += rowMaxH + NODE_GAP_Y
      }
      gm.nodeIds.forEach((id, i) => {
        const col = i % gm.cols
        const row = Math.floor(i / gm.cols)
        positions[id] = {
          x: baseX + GROUP_PAD + col * (NODE_W + NODE_GAP_X),
          y: rowOffsets[row],
        }
        nodeGroups[id] = groupIdx
        if (group.style === 'encrypted') encryptedIds.push(id)

        // Create frontend node from manifest definition
        const mNode = nodeMap[id] || {}
        const topoNode = topoMap[id]
        // Auto-generate label from ID if no label: sp-platform-armor → "Platform Armor"
        const autoLabel = id.replace(/^(sp|fr|bs|ig|vm|proxy|urlmap|mig|cert|ip|sm|ar|fw)-/, '')
          .replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
        manifestNodes.push({
          id,
          label: mNode.label || topoNode?.label || autoLabel,
          type: mNode.type || topoNode?.type || 'infra',
          status: topoNode?.status || (mNode.dynamic ? 'dynamic' : 'not monitored'),
          metrics: { ...topoNode?.metrics, ...(mNode.note ? { note: mNode.note } : {}) },
          source: 'manifest',
          project: manifest.product || '',
          env: manifest.environment || '',
          project_id: manifest.project_id || '',
          solution: manifest.solution || '',
          cost_yearly_usd: mNode.cost_yearly_usd || null,
          monitoring_logs: mNode.monitoring?.logs || null,
          children: topoNode?.children || mNode.children || null,
        })

        // Compute child positions for edge routing (REQ-702)
        // Children render inside parent — compute actual pixel offset for each child
        const nodeChildren = topoNode?.children || mNode.children
        if (nodeChildren && positions[id]) {
          const parentPos = positions[id]
          const totalH = nodeHeight({ children: nodeChildren })
          const topY = parentPos.y - totalH / 2
          let childOffsetY = NODE_H
          for (const child of nodeChildren) {
            const ch = childHeight(child)
            if (child.id) {
              positions[child.id] = { x: parentPos.x, y: topY + childOffsetY + ch / 2 }
            }
            // Grandchildren (e.g., ColdVault Platform inside Docker)
            if (child.children) {
              let gcOffsetY = CHILD_H
              for (const gc of child.children) {
                const gch = childHeight(gc)
                if (gc.id) {
                  positions[gc.id] = { x: parentPos.x, y: topY + childOffsetY + gcOffsetY + gch / 2 }
                }
                gcOffsetY += gch + CHILD_GAP
              }
            }
            childOffsetY += ch + CHILD_GAP
          }
        }
      })

      // Compute group cost (sum of children)
      const groupCost = gm.nodeIds.reduce((sum, nid) => {
        const c = (nodeMap[nid] || {}).cost_yearly_usd || 0
        return sum + c
      }, 0)

      groups.push({
        _name: group.name,
        label: group.label != null ? group.label : group.name,
        cost_yearly_usd: groupCost || null,
        encrypted: group.style === 'encrypted',
        partner: group.style === 'partner',
        planned: group.style === 'planned',
        vmGroup: group.style === 'encrypted',
        // REQ-213: pass through the parent node id (set on dynamic MIG groups)
        // so the click handler can open that node's modal.
        parent: group.parent || null,
      })
    }

    // Compute environment label — track which group indices belong to this env
    const envName = manifest.display_name || manifest.environment || manifest.product || ''
    const envGroupEnd = groups.length
    // Cost: sum only THIS environment's groups (not all groups across manifests)
    const envCost = groups.slice(envGroupStart).reduce((sum, g) => sum + (g.cost_yearly_usd || 0), 0)
    envLabels.push({
      label: envName,
      environment: manifest.environment || '',
      cost_yearly_usd: envCost || null,
      company: manifest.company || '',
      solution: manifest.solution || '',
      _groupStart: envGroupStart,
      _groupEnd: envGroupEnd,
    })

    envOffsetY = ry + ENV_GAP

    // Collect edges from manifest
    // Supports: node→node, @group→@group, @group→node, node→@group
    // Dot notation (pl-mig.api) skipped — creates spiderweb
    // @groupname → resolves to group center position
    for (const edge of (manifest.edges || [])) {
      const hasDot = edge.source?.includes('.') || edge.target?.includes('.')
      if (hasDot) continue
      manifestEdges.push({
        source: edge.source,
        target: edge.target,
        label: edge.label || '',
        status: edge.status || 'healthy',
        style: edge.style || 'default',  // 'default' | 'dashed' for deployment edges
      })
    }

    // Collect connects_to edges from static manifest nodes (REQ-702)
    for (const node of (manifest.nodes || [])) {
      if (node.connects_to && Array.isArray(node.connects_to)) {
        for (const target of node.connects_to) {
          manifestEdges.push({
            source: node.id,
            target,
            label: '',
            status: 'healthy',
            style: 'default',
          })
        }
      }
    }
  }

  // @group positions are computed dynamically in TopologyMap.jsx from live group bounds
  // (so they update when groups are dragged)

  // REQ-213: return null only when there's nothing renderable AND nothing to look up.
  // A manifest with only a parent node and an empty dynamic group still emits the
  // shell so callers can resolve manifestNodesById on click.
  if (Object.keys(positions).length === 0 && Object.keys(manifestNodesById).length === 0) {
    return null
  }
  return { positions, groups, nodeGroups, encryptedIds, manifestEdges, manifestNodes, envLabels, manifestNodesById }
}

// REQ-213: pure helper exported for unit testing.
// Builds the node record passed to handleNodeClick when the user clicks a dynamic
// group (e.g. the "Confidential VM (MIG)" group → opens pl-mig's modal).
//
// Merges manifest authority (label, type, monitoring, cost) with live topology data
// (status, metrics, last_checked). Uses nullish coalescing (??) so legitimate
// zero-cost / empty-string / false values aren't silently coerced to null.
export function buildParentNodeRecord(parentId, mNode, topoNode) {
  const monitoring = mNode?.monitoring
  return {
    id: parentId,
    label: mNode?.label ?? topoNode?.label ?? parentId,
    type: mNode?.type ?? topoNode?.type ?? 'mig',
    status: topoNode?.status ?? 'unknown',
    metrics: topoNode?.metrics ?? {},
    source: 'manifest',
    project_id: mNode?.project_id ?? topoNode?.project_id ?? '',
    project: topoNode?.project ?? '',
    env: topoNode?.env ?? '',
    solution: topoNode?.solution ?? '',
    cost_yearly_usd: mNode?.cost_yearly_usd ?? null,
    monitoring: monitoring ?? undefined,
    monitoring_logs: monitoring?.logs ?? null,
    last_checked: topoNode?.last_checked ?? null,
    gcp_resource_type: topoNode?.gcp_resource_type ?? null,
  }
}
