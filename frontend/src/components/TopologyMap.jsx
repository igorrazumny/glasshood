// File: frontend/src/components/TopologyMap.jsx
// Purpose: SVG topology visualization with zoom/pan, group boxes, and node selection

import { useState, useRef, useEffect, useCallback, useMemo } from 'react'
import TopologyNode, { nodeHeight, NODE_H, childHeight, CHILD_H, CHILD_GAP } from './TopologyNode'
import { computeManifestLayout, buildParentNodeRecord } from '../utils/manifestLayout'
import { useNodePositions } from '../hooks/useNodePositions'

// Dynamic live layout — HARDWARE ONLY
// Shows: Cloud Armor, LB chain, MIG, VMs, GPUs per project
// Excludes: LLM APIs, software components, planned infrastructure
function computeLiveLayout(nodes) {
  if (!nodes || nodes.length === 0) return null

  const positions = {}
  const nodeGroups = {}
  const encryptedIds = []

  // --- Step 1: Partition nodes by project environment ---
  const projectMarkers = []
  const projectResources = {}  // project_id → [hardware nodes]

  for (const node of nodes) {
    if (node.type === 'project') {
      projectMarkers.push(node)
    } else if (node.type === 'llm' || node.type === 'rag' || node.type === 'db' ||
               node.type === 'nginx' || node.type === 'storage') {
      // Skip software components — hardware only
      continue
    } else {
      // Hardware node — group by project
      const pid = node.project_id || node.project || 'unknown'
      ;(projectResources[pid] = projectResources[pid] || []).push(node)
    }
  }

  // --- Step 2: Per-project layout (each project gets its own section) ---
  // Sort projects: ones with resources first, then alphabetical
  const sortedProjects = [...projectMarkers].sort((a, b) => {
    const aR = (projectResources[a.project_id] || []).length
    const bR = (projectResources[b.project_id] || []).length
    if (aR && !bR) return -1; if (!aR && bR) return 1
    return (a.label || '').localeCompare(b.label || '')
  })

  // Also include hardware nodes not tied to any project marker
  const allProjectIds = new Set(sortedProjects.map(p => p.project_id))
  for (const pid of Object.keys(projectResources)) {
    if (!allProjectIds.has(pid)) {
      // Create a virtual project marker for ungrouped hardware
      sortedProjects.unshift({
        id: `proj_${pid}`, label: pid, project_id: pid, type: 'project'
      })
    }
  }

  const VS = 70
  const CX = { ingress: 0, lb: 240, compute: 480, gpu: 720 }
  let currentY = 60
  let groupIdx = 0

  for (const proj of sortedProjects) {
    const resources = projectResources[proj.project_id] || []
    if (resources.length === 0) continue  // skip empty projects

    // Classify resources into columns
    const cols = { ingress: [], lb: [], compute: [], gpu: [] }
    for (const node of resources) {
      const id = node.id
      if (id.startsWith('fr-') || id.startsWith('sp-')) cols.ingress.push(node)
      else if (id.startsWith('proxy-') || id.startsWith('urlmap-') || id.startsWith('bs-') || id.startsWith('ig-')) cols.lb.push(node)
      else if (id.startsWith('vm-')) cols.compute.push(node)
      else if (node.type === 'gpu') cols.gpu.push(node)
      else cols.compute.push(node)  // fallback: put in compute column
    }

    // Project header
    const sectionStartY = currentY
    positions[proj.id] = { x: CX.lb + 120, y: currentY }
    nodeGroups[proj.id] = groupIdx
    currentY += 50

    // Layout each column
    const colStartY = currentY
    let maxColY = currentY

    for (const [colName, colNodes] of Object.entries(cols)) {
      const x = CX[colName]
      colNodes.forEach((node, i) => {
        const y = colStartY + i * VS
        positions[node.id] = { x, y }
        nodeGroups[node.id] = groupIdx
        encryptedIds.push(node.id)
        if (y + VS > maxColY) maxColY = y + VS
      })
    }

    currentY = maxColY + 40  // gap between projects
    groupIdx++
  }

  // Build group labels from projects
  const groups = sortedProjects
    .filter(p => (projectResources[p.project_id] || []).length > 0)
    .map(p => ({
      label: p.label || p.project_id,
      encrypted: true,
      vmGroup: true,
    }))

  return { positions, groups, nodeGroups, encryptedIds }
}

// Demo mode positions (39 nodes — top: services, bottom: GPU infrastructure)
const DEMO_POSITIONS = {
  lb:         { x: 100, y: 120 },
  auth0:      { x: 100, y: 260 },
  nginx:      { x: 280, y: 120 },
  mig:        { x: 280, y: 260 },
  vm1:        { x: 460, y: 70 },
  vm2:        { x: 460, y: 200 },
  vm3:        { x: 460, y: 330 },
  faiss:      { x: 640, y: 70 },
  cloudsql:   { x: 640, y: 200 },
  embeddings: { x: 640, y: 330 },
  llm_router:       { x: 810, y: 200 },
  gemini_3_flash:   { x: 930, y: 10 },
  gemini_3_pro:     { x: 930, y: 60 },
  claude_opus_45:   { x: 930, y: 110 },
  claude_sonnet_45: { x: 930, y: 160 },
  claude_haiku_45:  { x: 930, y: 210 },
  gpt52:            { x: 930, y: 260 },
  gpt5_mini:        { x: 930, y: 310 },
  grok4:            { x: 930, y: 360 },
  grok_fast:        { x: 1080, y: 10 },
  qwen3_235b:       { x: 1080, y: 60 },
  qwen3_next:       { x: 1080, y: 110 },
  qwen3_coder:      { x: 1080, y: 160 },
  llama4_maverick:  { x: 1080, y: 210 },
  llama4_scout:     { x: 1080, y: 260 },
  mistral_medium3:  { x: 1080, y: 310 },
  minimax_m2:       { x: 1080, y: 360 },
  model_glm47_flash: { x: 140, y: 520 },
  model_ministral3:  { x: 140, y: 620 },
  model_qwen35:      { x: 530, y: 520 },
  model_glm5:        { x: 930, y: 520 },
  gpu_h200_0: { x: 140, y: 720 },
  gpu_h200_1: { x: 410, y: 620 },
  gpu_h200_2: { x: 530, y: 620 },
  gpu_h200_3: { x: 650, y: 620 },
  gpu_h200_4: { x: 530, y: 720 },
  gpu_h200_5: { x: 820, y: 620 },
  gpu_h200_6: { x: 940, y: 620 },
  gpu_h200_7: { x: 1060, y: 620 },
}

// REQ-005 + REQ-009 Phase 4b: palette aligned to the GxP architecture
// reference slide and now theme-aware via CSS vars. The hex values live
// in index.css :root (light) and .dark (dark). Names stay for backward
// compat with existing call sites; values flip with the theme.
const CV_ACCENT = 'var(--canvas-accent-primary)'   // royal blue / ColdVault cyan in dark
const PARTNER_COLOR = 'var(--canvas-accent-partner)'  // Solace green (brighter on dark)
const PLANNED_COLOR = 'var(--canvas-accent-planned)'  // slate (quieter on dark)

// Hex anchors retained for the cross-file STATUS_COLORS invariant test
// (light-theme values; dark overrides live in index.css .dark).
// eslint-disable-next-line no-unused-vars
const CANVAS_PALETTE_HEX_REFERENCE = {
  CV_ACCENT: '#2563eb',
  PARTNER_COLOR: '#65a30d',
  PLANNED_COLOR: '#94a3b8',
}

const DEMO_GROUPS = [
  { label: 'Ingress',    x: 40,   y: 70,  w: 120, h: 240 },
  { label: 'Proxy',      x: 220,  y: 70,  w: 120, h: 240 },
  { label: 'Compute',    x: 400,  y: 20,  w: 120, h: 360 },
  { label: 'Data',       x: 580,  y: 20,  w: 120, h: 360 },
  { label: 'LLM APIs',   x: 770,  y: -20, w: 370, h: 430 },
  { label: 'Light Models (H200 #0)', x: 60,  y: 470, w: 220, h: 300 },
  { label: 'Qwen3.5-397B FP8 (H200 #1-#4)', x: 340, y: 470, w: 370, h: 300 },
  { label: 'GLM-5-744B FP4 (H200 #5-#7)', x: 760, y: 470, w: 360, h: 210 },
]

// Node-to-group membership — live mode computed dynamically, demo mode hardcoded

const DEMO_NODE_GROUPS = {
  lb: 0, auth0: 0,
  nginx: 1, mig: 1,
  vm1: 2, vm2: 2, vm3: 2,
  faiss: 3, cloudsql: 3, embeddings: 3,
  llm_router: 4, gemini_3_flash: 4, gemini_3_pro: 4, claude_opus_45: 4,
  claude_sonnet_45: 4, claude_haiku_45: 4, gpt52: 4, gpt5_mini: 4, grok4: 4,
  grok_fast: 4, qwen3_235b: 4, qwen3_next: 4, qwen3_coder: 4,
  llama4_maverick: 4, llama4_scout: 4, mistral_medium3: 4, minimax_m2: 4,
  model_glm47_flash: 5, model_ministral3: 5, gpu_h200_0: 5,
  model_qwen35: 6, gpu_h200_1: 6, gpu_h200_2: 6, gpu_h200_3: 6, gpu_h200_4: 6,
  model_glm5: 7, gpu_h200_5: 7, gpu_h200_6: 7, gpu_h200_7: 7,
}

// REQ-005 + REQ-009 Phase 4b: status colors via CSS vars so dark mode can
// brighten if needed. Hex anchors retained in STATUS_COLORS_HEX_REFERENCE
// below for the cross-file invariant test (TopologyNode mirrors this).
const STATUS_COLORS = {
  healthy: 'var(--status-healthy)',
  deployed: 'var(--status-healthy)',
  degraded: 'var(--status-degraded)',
  error: 'var(--status-error)',
  disconnected: 'var(--status-inactive)',
  stale: 'var(--status-degraded)',
  unknown: 'var(--status-inactive)',
  planned: 'var(--status-inactive)',
}

// Cross-file invariant anchor. TopologyNode has the matching block.
// Runtime reads STATUS_COLORS above (CSS vars); this exists so the
// consistency test can prove the two files' hex tables align.
// eslint-disable-next-line no-unused-vars
const STATUS_COLORS_HEX_REFERENCE = {
  healthy: '#16a34a',
  deployed: '#16a34a',
  degraded: '#ca8a04',
  error: '#dc2626',
  disconnected: '#94a3b8',
  stale: '#ca8a04',
  unknown: '#94a3b8',
  planned: '#94a3b8',
}

function EdgeLine({ edge, positions, index = 0 }) {
  const from = positions[edge.source]
  const to = positions[edge.target]
  if (!from || !to) return null

  const isDeployEdge = edge.style === 'dashed'
  // REQ-005 + REQ-009 Phase 4b: deploy-edge gray via CSS var so dark mode
  // can substitute a brighter slate.
  const color = isDeployEdge ? 'var(--edge-deploy)' : (STATUS_COLORS[edge.status] || STATUS_COLORS.unknown)
  const isDashed = isDeployEdge || edge.status === 'disconnected' || edge.status === 'error'

  const mx = (from.x + to.x) / 2
  const my = (from.y + to.y) / 2
  const dx = to.x - from.x
  const dy = to.y - from.y
  const curve = 0.06 + (index % 5) * 0.02
  const cx = mx - dy * curve
  const cy = my + dx * curve

  const pathId = `edge-${edge.source}-${edge.target}`
  const pathD = `M ${from.x} ${from.y} Q ${cx} ${cy} ${to.x} ${to.y}`

  return (
    <g>
      {/* Edge label as tooltip only — hover to see */}
      {edge.label && <title>{`${edge.source} → ${edge.target}: ${edge.label}`}</title>}
      <path
        id={pathId}
        d={pathD}
        fill="none"
        stroke={color}
        strokeWidth={1.2}
        strokeDasharray={isDashed ? '6 4' : 'none'}
        opacity={isDashed ? 0.35 : 0.45}
      />
    </g>
  )
}

const DEMO_VB = { x: -40, y: -30, w: 1300, h: 830 }
const LIVE_VB = { x: -80, y: -20, w: 1200, h: 800 }

export default function TopologyMap({ data, error, isDemo, hideCosts, onNodeSelect, focusProjectId, manifests }) {
  const [selected, setSelected] = useState(null)
  const defaultVB = isDemo ? DEMO_VB : LIVE_VB
  const [viewBox, setViewBox] = useState(defaultVB)
  const svgRef = useRef(null)
  const containerRef = useRef(null)
  const isPanning = useRef(false)
  const draggingNode = useRef(null)
  const draggingGroup = useRef(null)
  const panStart = useRef({ x: 0, y: 0 })
  const dragDist = useRef(0)

  // Performance: direct DOM updates bypass React during pan/zoom interaction
  const viewBoxRef = useRef(defaultVB)
  const wheelEndRef = useRef(null)
  const interactingRef = useRef(false)
  const rectCacheRef = useRef(null)

  // Layout: manifests are source of truth when available
  // Manifest nodes are canonical — no sparse threshold needed
  const manifestLayout = (!isDemo && Array.isArray(manifests) && manifests.length > 0)
    ? computeManifestLayout(data?.nodes, manifests)
    : null
  // When manifests are expected (not demo), ONLY use manifest layout
  // Don't fall back to computeLiveLayout — it shows org-discovery VMs
  const liveLayout = (!isDemo && data)
    ? (manifestLayout || (manifests === null ? computeLiveLayout(data.nodes) : null))
    : null

  // When manifest layout is active, use manifest-generated nodes as the node list
  const manifestNodeIds = null  // no filtering — manifest nodes ARE the nodes
  const basePositions = isDemo ? DEMO_POSITIONS : (liveLayout?.positions || {})
  const activeGroups = isDemo ? DEMO_GROUPS : (liveLayout?.groups || [])
  const activeNodeGroups = isDemo ? DEMO_NODE_GROUPS : (liveLayout?.nodeGroups || {})
  const encryptedNodeIds = liveLayout?.encryptedIds || []
  // REQ-213: full id→manifest-node map for resolving dynamic-group parents on click.
  const manifestNodesById = liveLayout?.manifestNodesById || {}

  // Single source of truth for positions — default + saved + active drag
  const { positions, startDrag, updateDrag, endDrag, resetPositions } = useNodePositions(basePositions)

  // Direct DOM viewBox update — bypasses React reconciliation for smooth 60fps interaction
  const applyViewBox = useCallback((vb) => {
    viewBoxRef.current = vb
    const svg = svgRef.current
    if (svg) svg.setAttribute('viewBox', `${vb.x} ${vb.y} ${vb.w} ${vb.h}`)
  }, [])

  const startInteraction = useCallback(() => {
    if (!interactingRef.current) {
      interactingRef.current = true
      svgRef.current?.pauseAnimations?.()
    }
  }, [])

  const endInteraction = useCallback(() => {
    interactingRef.current = false
    svgRef.current?.unpauseAnimations?.()
    setViewBox(viewBoxRef.current)
  }, [])

  // Sync React state → ref when state changes externally (buttons, focus)
  useEffect(() => {
    if (!interactingRef.current) viewBoxRef.current = viewBox
  }, [viewBox])

  // Invalidate rect cache on resize
  useEffect(() => {
    const onResize = () => { rectCacheRef.current = null }
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  // Zoom to focused project or reset to full view.
  // focusHasPosition re-triggers the effect when topology loads and the project's
  // position becomes available (solves: select project before data loads → zoom missed).
  // Full positions object excluded to avoid re-snapping on every poll cycle.
  // Zoom to solution when selected from left panel
  useEffect(() => {
    if (focusProjectId === null) {
      if (!isDemo) setViewBox(defaultVB)
      return
    }
    // Find bounds of all groups belonging to this solution's product
    const product = focusProjectId.replace('manifest-', '').replace(/-prod|-val|-staging/g, '')
    const solutionGroups = effectiveGroups.filter((g, i) => {
      // Match groups by checking which envLabel they belong to
      const envLabel = manifestLayout?.envLabels?.find(e => e.label?.toLowerCase().includes(product))
      if (!envLabel) return false
      return i >= (envLabel._groupStart || 0) && i < (envLabel._groupEnd || effectiveGroups.length)
    })
    if (solutionGroups.length === 0) {
      // Fallback: try to find any group with matching nodes
      setViewBox(defaultVB)
      return
    }
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
    for (const g of solutionGroups) {
      minX = Math.min(minX, g.x); minY = Math.min(minY, g.y)
      maxX = Math.max(maxX, g.x + g.w); maxY = Math.max(maxY, g.y + g.h)
    }
    if (minX === Infinity) return
    const pad = 60
    setViewBox({ x: minX - pad, y: minY - pad - 30, w: (maxX - minX) + pad * 2, h: (maxY - minY) + pad * 2 + 30 })
  }, [focusProjectId])

  // Wheel zoom — direct DOM updates bypass React for smooth 60fps
  const dataReady = !!data
  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const onWheel = (e) => {
      e.preventDefault()
      e.stopPropagation()
      startInteraction()

      // Cache rect to avoid layout thrashing during gesture
      if (!rectCacheRef.current) rectCacheRef.current = container.getBoundingClientRect()
      const rect = rectCacheRef.current
      const mx = (e.clientX - rect.left) / rect.width
      const my = (e.clientY - rect.top) / rect.height
      const vb = viewBoxRef.current

      let next
      if (e.ctrlKey || e.metaKey) {
        // Smooth continuous zoom — 0.008 = user-confirmed good sensitivity
        // normalize deltaMode (0=px trackpad, 1=line mouse, 2=page)
        const dy = e.deltaMode === 1 ? e.deltaY * 4 : e.deltaMode === 2 ? e.deltaY * 25 : e.deltaY
        const scale = Math.exp(dy * 0.008)
        const px = vb.x + mx * vb.w
        const py = vb.y + my * vb.h
        const nw = Math.max(300, Math.min(8000, vb.w * scale))
        const nh = Math.max(200, Math.min(5200, vb.h * scale))
        const r = nw / vb.w
        next = { x: px - (px - vb.x) * r, y: py - (py - vb.y) * r, w: nw, h: nh }
      } else {
        // Two-finger scroll: pan in both directions (vertical + horizontal)
        const scaleX = vb.w / rect.width
        const scaleY = vb.h / rect.height
        next = { ...vb, x: vb.x + e.deltaX * scaleX, y: vb.y + e.deltaY * scaleY }
      }

      applyViewBox(next)

      // Commit to React state when gesture stops
      clearTimeout(wheelEndRef.current)
      wheelEndRef.current = setTimeout(() => {
        rectCacheRef.current = null
        endInteraction()
      }, 120)
    }
    container.addEventListener('wheel', onWheel, { passive: false })
    return () => {
      container.removeEventListener('wheel', onWheel)
      clearTimeout(wheelEndRef.current)
    }
  }, [dataReady, applyViewBox, startInteraction, endInteraction])

  // Touch handlers for mobile pinch-to-zoom and drag-to-pan
  const touchRef = useRef({ touches: [], lastDist: 0, lastCenter: null })
  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const getTouchDist = (t1, t2) => Math.hypot(t2.clientX - t1.clientX, t2.clientY - t1.clientY)
    const getTouchCenter = (t1, t2) => ({ x: (t1.clientX + t2.clientX) / 2, y: (t1.clientY + t2.clientY) / 2 })

    const onTouchStart = (e) => {
      if (e.touches.length === 1) {
        panStart.current = { x: e.touches[0].clientX, y: e.touches[0].clientY }
        isPanning.current = true
      } else if (e.touches.length === 2) {
        e.preventDefault()
        isPanning.current = false
        touchRef.current.lastDist = getTouchDist(e.touches[0], e.touches[1])
        touchRef.current.lastCenter = getTouchCenter(e.touches[0], e.touches[1])
      }
    }

    const onTouchMove = (e) => {
      if (e.touches.length === 2) {
        e.preventDefault()
        startInteraction()
        const dist = getTouchDist(e.touches[0], e.touches[1])
        const center = getTouchCenter(e.touches[0], e.touches[1])
        const rect = container.getBoundingClientRect()
        const mx = (center.x - rect.left) / rect.width
        const my = (center.y - rect.top) / rect.height

        if (touchRef.current.lastDist > 0) {
          const scale = touchRef.current.lastDist / dist
          const vb = viewBoxRef.current
          const px = vb.x + mx * vb.w
          const py = vb.y + my * vb.h
          const nw = Math.max(300, Math.min(8000, vb.w * scale))
          const nh = Math.max(200, Math.min(5200, vb.h * scale))
          const r = nw / vb.w
          applyViewBox({ x: px - (px - vb.x) * r, y: py - (py - vb.y) * r, w: nw, h: nh })
        }
        if (touchRef.current.lastCenter) {
          const dx = center.x - touchRef.current.lastCenter.x
          const dy = center.y - touchRef.current.lastCenter.y
          const vb = viewBoxRef.current
          applyViewBox({
            ...vb,
            x: vb.x - dx / rect.width * vb.w,
            y: vb.y - dy / rect.height * vb.h,
          })
        }
        touchRef.current.lastDist = dist
        touchRef.current.lastCenter = center
      } else if (e.touches.length === 1 && isPanning.current) {
        startInteraction()
        const svg = svgRef.current
        if (!svg) return
        const rect = svg.getBoundingClientRect()
        const vb = viewBoxRef.current
        const dx = (e.touches[0].clientX - panStart.current.x) / rect.width * vb.w
        const dy = (e.touches[0].clientY - panStart.current.y) / rect.height * vb.h
        applyViewBox({ ...vb, x: vb.x - dx, y: vb.y - dy })
        panStart.current = { x: e.touches[0].clientX, y: e.touches[0].clientY }
      }
    }

    const onTouchEnd = () => {
      isPanning.current = false
      touchRef.current.lastDist = 0
      touchRef.current.lastCenter = null
      if (interactingRef.current) endInteraction()
    }

    container.addEventListener('touchstart', onTouchStart, { passive: false })
    container.addEventListener('touchmove', onTouchMove, { passive: false })
    container.addEventListener('touchend', onTouchEnd)
    return () => {
      container.removeEventListener('touchstart', onTouchStart)
      container.removeEventListener('touchmove', onTouchMove)
      container.removeEventListener('touchend', onTouchEnd)
    }
  }, [dataReady])

  const onMouseDown = (e) => {
    if (e.button !== 0) return
    // Don't start panning if a node or group drag already claimed this event
    if (draggingNode.current || draggingGroup.current !== null) return
    isPanning.current = true
    panStart.current = { x: e.clientX, y: e.clientY }
    dragDist.current = 0
  }

  const onNodeMouseDown = (e, nodeId) => {
    if (e.button !== 0) return
    e.stopPropagation()
    draggingNode.current = nodeId
    draggingGroup.current = null
    isPanning.current = false
    panStart.current = { x: e.clientX, y: e.clientY }
    dragDist.current = 0
    // Convert screen coords to SVG coords for the hook
    const svg = svgRef.current
    const rect = svg?.getBoundingClientRect()
    if (rect) {
      const vb = viewBoxRef.current
      const mx = (e.clientX - rect.left) / rect.width * vb.w + vb.x
      const my = (e.clientY - rect.top) / rect.height * vb.h + vb.y
      startDrag([nodeId], mx, my)
    }
  }

  const onGroupMouseDown = (e, groupIdx) => {
    if (e.button !== 0) return
    e.stopPropagation()
    draggingGroup.current = groupIdx
    draggingNode.current = null
    isPanning.current = false
    panStart.current = { x: e.clientX, y: e.clientY }
    dragDist.current = 0
    // Collect all node IDs in this group
    const groupNodeIds = Object.entries(activeNodeGroups)
      .filter(([, gi]) => gi === groupIdx).map(([nid]) => nid)
    const svg = svgRef.current
    const rect = svg?.getBoundingClientRect()
    if (rect && groupNodeIds.length > 0) {
      const vb = viewBoxRef.current
      const mx = (e.clientX - rect.left) / rect.width * vb.w + vb.x
      const my = (e.clientY - rect.top) / rect.height * vb.h + vb.y
      startDrag(groupNodeIds, mx, my)
    }
  }

  const onMouseMove = (e) => {
    const svg = svgRef.current
    if (!svg) return
    const rect = svg.getBoundingClientRect()
    const vbCurrent = viewBoxRef.current
    dragDist.current += Math.abs(e.clientX - panStart.current.x) + Math.abs(e.clientY - panStart.current.y)

    if (draggingNode.current || draggingGroup.current !== null) {
      const mx = (e.clientX - rect.left) / rect.width * vbCurrent.w + vbCurrent.x
      const my = (e.clientY - rect.top) / rect.height * vbCurrent.h + vbCurrent.y
      updateDrag(mx, my)
    } else if (isPanning.current) {
      const dx = (e.clientX - panStart.current.x) / rect.width * vbCurrent.w
      const dy = (e.clientY - panStart.current.y) / rect.height * vbCurrent.h
      startInteraction()
      applyViewBox({ ...vbCurrent, x: vbCurrent.x - dx, y: vbCurrent.y - dy })
    } else {
      return
    }
    panStart.current = { x: e.clientX, y: e.clientY }
  }

  const onMouseUp = () => {
    if (draggingNode.current || draggingGroup.current !== null) endDrag()
    if (isPanning.current && interactingRef.current) endInteraction()
    isPanning.current = false; draggingNode.current = null; draggingGroup.current = null
  }

  const handleNodeClick = (node) => {
    if (dragDist.current > 5) return
    const newSelected = selected === node.id ? null : node.id
    setSelected(newSelected)
    if (onNodeSelect) onNodeSelect(newSelected ? node : null)
  }

  const resetView = () => { setViewBox(defaultVB) }

  if (error && !data) {
    return (
      <div className="h-full flex items-center justify-center text-red-400">
        Connection error: {error}
      </div>
    )
  }

  if (!data) {
    return (
      <div className="h-full flex items-center justify-center text-gray-500">
        Loading topology...
      </div>
    )
  }

  const allNodes = data.nodes || []
  const allEdges = data.edges || []
  // When manifests are active, use manifest-generated nodes as canonical source
  const nodes = manifestLayout?.manifestNodes?.length > 0
    ? manifestLayout.manifestNodes
    : allNodes

  // Build resolved positions: original positions + REAL child positions within parent box.
  // Children are rendered inside their parent — compute actual visual offset for edge endpoints.
  const resolvedPositions = { ...positions }
  const _addChildPositions = (parentPos, parentTotalH, children) => {
    if (!parentPos || !children) return
    const topY = parentPos.y - parentTotalH / 2  // top of parent box
    let offsetY = NODE_H  // children start below node header
    for (const child of children) {
      const ch = childHeight(child)
      if (child.id && !resolvedPositions[child.id]) {
        resolvedPositions[child.id] = {
          x: parentPos.x,
          y: topY + offsetY + ch / 2,
        }
      }
      // Recurse: nested children positioned inside this child
      if (child.children) {
        const childTopY = topY + offsetY
        let nestedOffsetY = CHILD_H  // grandchildren start below child header
        for (const gc of child.children) {
          const gch = childHeight(gc)
          if (gc.id && !resolvedPositions[gc.id]) {
            resolvedPositions[gc.id] = {
              x: parentPos.x,
              y: childTopY + nestedOffsetY + gch / 2,
            }
          }
          nestedOffsetY += gch + CHILD_GAP
        }
      }
      offsetY += ch + CHILD_GAP
    }
  }
  for (const node of nodes) {
    if (node.children) {
      const pos = resolvedPositions[node.id]
      _addChildPositions(pos, nodeHeight(node), node.children)
    }
  }
  for (const node of allNodes) {
    if (node.children && nodes !== allNodes) {
      const pos = resolvedPositions[node.id]
      if (pos) _addChildPositions(pos, nodeHeight(node), node.children)
    }
  }

  // Edges: manifest edges when available, otherwise discovery edges (filtered to positioned nodes)
  // Keep @group edges even though they don't have positions yet — resolved after effectiveGroups
  const manifestEdges = (manifestLayout?.manifestEdges || [])
    .filter(e => (e.source?.startsWith('@') || resolvedPositions[e.source]) && (e.target?.startsWith('@') || resolvedPositions[e.target]))
  // Merge manifest edges + topology edges for discovered nodes (VMs).
  // Allow @group targets — resolved after effectiveGroups bounds are computed.
  const topoEdgesForDiscovered = allEdges.filter(e =>
    resolvedPositions[e.source] &&
    (e.target?.startsWith('@') || resolvedPositions[e.target]) &&
    !manifestEdges.some(me => me.source === e.source && me.target === e.target)
  )
  const edges = manifestEdges.length > 0
    ? [...manifestEdges, ...topoEdgesForDiscovered]
    : allEdges.filter(e =>
        resolvedPositions[e.source] &&
        (e.target?.startsWith('@') || resolvedPositions[e.target]))
  const vb = `${viewBox.x} ${viewBox.y} ${viewBox.w} ${viewBox.h}`

  // Compute effective group bounds from node positions (accounts for nested node heights)
  const nodeById = {}
  for (const n of nodes) nodeById[n.id] = n
  const effectiveGroups = activeGroups.map((g, idx) => {
    const halfW = 70
    const padX = 20, padY = 20
    const labelH = 25
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
    // Track worst member status to color the group border by health
    let groupHealth = null  // null = no data
    const statusPriority = { healthy: 0, unknown: 1, disabled: 1, degraded: 2, error: 3 }
    for (const [nid, gi] of Object.entries(activeNodeGroups)) {
      if (gi !== idx) continue
      const p = positions[nid]
      if (!p) continue
      const node = nodeById[nid]
      const halfH = (node ? nodeHeight(node) : NODE_H) / 2
      minX = Math.min(minX, p.x - halfW)
      minY = Math.min(minY, p.y - halfH)
      maxX = Math.max(maxX, p.x + halfW)
      maxY = Math.max(maxY, p.y + halfH)
      // Aggregate worst status
      const s = node?.status
      if (s && s !== 'not monitored') {
        if (groupHealth === null ||
            (statusPriority[s] ?? 1) > (statusPriority[groupHealth] ?? 1)) {
          groupHealth = s
        }
      }
    }
    if (minX === Infinity) return null
    return {
      ...g,
      x: minX - padX,
      y: minY - padY - labelH,
      w: (maxX - minX) + padX * 2,
      h: (maxY - minY) + padY * 2 + labelH,
      _idx: idx,
      _health: groupHealth,
    }
  }).filter(Boolean)

  // Resolve overlapping group boxes — push apart vertically (2 passes for cascading)
  const overlapMargin = 15
  for (let pass = 0; pass < 2; pass++) {
    for (let i = 0; i < effectiveGroups.length; i++) {
      for (let j = i + 1; j < effectiveGroups.length; j++) {
        const a = effectiveGroups[i], b = effectiveGroups[j]
        const xOverlap = a.x < b.x + b.w && b.x < a.x + a.w
        const yOverlap = a.y < b.y + b.h && b.y < a.y + a.h
        if (xOverlap && yOverlap) {
          const pushDown = (a.y + a.h) - b.y + overlapMargin
          if (pushDown > 0) {
            effectiveGroups[j] = { ...b, y: b.y + pushDown }
            // Move nodes in pushed group
            for (const [nid, gi] of Object.entries(activeNodeGroups)) {
              if (gi === b._idx && positions[nid]) {
                positions[nid] = { ...positions[nid], y: positions[nid].y + pushDown }
              }
            }
          }
        }
      }
    }
  }

  // Resolve @group edges: compute boundary positions from live effectiveGroups
  // Source group: right-center. Target group: left-center.
  const groupBoundsMap = {}
  for (const g of effectiveGroups) {
    if (g._name) groupBoundsMap[g._name] = g
  }
  const resolvedEdges = edges.map(e => {
    const srcGroup = e.source?.startsWith('@') ? groupBoundsMap[e.source.slice(1)] : null
    const tgtGroup = e.target?.startsWith('@') ? groupBoundsMap[e.target.slice(1)] : null
    if (!srcGroup && !tgtGroup) return e  // normal node-to-node edge
    const resolvedSource = srcGroup
      ? `__grp_${e.source.slice(1)}_R`
      : e.source
    const resolvedTarget = tgtGroup
      ? `__grp_${e.target.slice(1)}_L`
      : e.target
    // Create temporary positions for group boundary points (in resolvedPositions, not base positions)
    if (srcGroup) {
      resolvedPositions[resolvedSource] = { x: srcGroup.x + srcGroup.w, y: srcGroup.y + srcGroup.h / 2 }
    }
    if (tgtGroup) {
      resolvedPositions[resolvedTarget] = { x: tgtGroup.x, y: tgtGroup.y + tgtGroup.h / 2 }
    }
    return { ...e, source: resolvedSource, target: resolvedTarget }
  }).filter(e => resolvedPositions[e.source] && resolvedPositions[e.target])

  return (
    <div ref={containerRef} className="h-full bg-card dark:bg-purple-950 border border-border dark:border-purple-700 rounded-lg p-2 relative" style={{ touchAction: 'none', overscrollBehavior: 'contain' }}>
      <svg
        ref={svgRef}
        viewBox={vb}
        className="w-full h-full"
        style={{ minHeight: '400px', cursor: isPanning.current ? 'grabbing' : 'grab', touchAction: 'none', overscrollBehavior: 'none' }}
        onMouseDown={onMouseDown}
        onMouseMove={onMouseMove}
        onMouseUp={onMouseUp}
        onMouseLeave={onMouseUp}
      >
        <defs>
          {/* REQ-005 + REQ-009 Phase 4b: grid + arrowhead via CSS vars so
              dark mode can substitute purple-700 grid + brighter arrowhead. */}
          <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
            <path d="M 40 0 L 0 0 0 40" fill="none" stroke="var(--canvas-grid)" strokeWidth={0.5} />
          </pattern>
          <marker id="arrowhead" markerWidth="6" markerHeight="4" refX="6" refY="2" orient="auto">
            <polygon points="0 0, 6 2, 0 4" fill="var(--edge-arrow)" />
          </marker>
          {/* REQ-011: glow filters declared ONCE at the SVG root, referenced
              by per-node GLOW_FILTER map via url(#…). Previously each
              TopologyNode injected its own <defs> with the same static IDs,
              which is undefined behaviour per the SVG spec.
              REQ-012: floodColor reads CSS vars so dark mode can substitute
              brighter hues that read against the purple-950 canvas. */}
          <filter id="glow-yellow"><feDropShadow dx="0" dy="0" stdDeviation="4" floodColor="var(--glow-degraded)" floodOpacity="0.35" /></filter>
          <filter id="glow-red"><feDropShadow dx="0" dy="0" stdDeviation="4" floodColor="var(--glow-error)" floodOpacity="0.35" /></filter>
        </defs>
        <rect x={-400} y={-500} width="4000" height="4000" fill="url(#grid)" />

        {/* Hierarchy boundaries: Company → Solution → Environment */}
        {!isDemo && effectiveGroups.length > 0 && (() => {
          const formatCost = (c) => {
            if (hideCosts) return ''
            return c >= 1000 ? `$${(c/1000).toFixed(0)}k/yr` : c > 0 ? `$${c}/yr` : ''
          }
          const envLabels = manifestLayout?.envLabels || []
          const pad = { env: 15, sol: 30, co: 45 }, labelH = 18

          // Compute bounds per environment from its own groups
          const envBounds = envLabels.map(env => {
            let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
            for (let gi = env._groupStart || 0; gi < (env._groupEnd || effectiveGroups.length); gi++) {
              const g = effectiveGroups[gi]
              if (!g) continue
              minX = Math.min(minX, g.x); minY = Math.min(minY, g.y)
              maxX = Math.max(maxX, g.x + g.w); maxY = Math.max(maxY, g.y + g.h)
            }
            return { ...env, minX, minY, maxX, maxY }
          }).filter(b => b.minX !== Infinity)

          // Per-solution: merge env bounds
          const solutions = {}
          for (const eb of envBounds) {
            const sol = eb.solution || eb.label
            if (!solutions[sol]) solutions[sol] = { minX: Infinity, minY: Infinity, maxX: -Infinity, maxY: -Infinity, cost: 0, company: eb.company }
            solutions[sol].minX = Math.min(solutions[sol].minX, eb.minX)
            solutions[sol].minY = Math.min(solutions[sol].minY, eb.minY)
            solutions[sol].maxX = Math.max(solutions[sol].maxX, eb.maxX)
            solutions[sol].maxY = Math.max(solutions[sol].maxY, eb.maxY)
            solutions[sol].cost += eb.cost_yearly_usd || 0
          }

          // Company: merge all solutions
          let coMinX = Infinity, coMinY = Infinity, coMaxX = -Infinity, coMaxY = -Infinity
          let totalCost = 0, company = '9RobotsAI'
          for (const sol of Object.values(solutions)) {
            coMinX = Math.min(coMinX, sol.minX); coMinY = Math.min(coMinY, sol.minY)
            coMaxX = Math.max(coMaxX, sol.maxX); coMaxY = Math.max(coMaxY, sol.maxY)
            totalCost += sol.cost; company = sol.company || company
          }
          if (coMinX === Infinity) return null

          // REQ-006: the `frameOpacity` argument applies ONLY to the wrapper
          // <rect> stroke so the boundary stays a quiet hint, not a hard
          // frame. Label opacity is hardcoded to 1.0 and cost opacity to 0.85
          // so the L1/L2/L3 titles ("9RobotsAI — All Projects" / solution /
          // environment) read clearly against the cream canvas regardless of
          // how faint the stroke is. Param was renamed from `opacity` to
          // make the partial-application explicit (9r round-1 feedback).
          const drawBox = (x, y, w, h, color, dash, frameOpacity, sw, label, cost, rx) => (
            <g>
              <rect x={x} y={y} width={w} height={h} rx={rx}
                fill="none" stroke={color} strokeWidth={sw} strokeDasharray={dash} opacity={frameOpacity} />
              <text x={x + 10} y={y + 14} fill={color} fontSize={rx > 10 ? 14 : rx > 8 ? 12 : 10}
                fontWeight={700} opacity={1}>{label}</text>
              {cost && <text x={x + w - 10} y={y + 14} textAnchor="end"
                fill={color} fontSize={rx > 10 ? 11 : 9} fontFamily="monospace" opacity={0.85}>{cost}</text>}
            </g>
          )

          return (
            <g>
              {/* User feedback 2026-05-24: L1/L2/L3 hierarchical boundary
                  labels are STRUCTURAL — they describe the company /
                  solution / environment nesting, not status. Color should
                  be reserved for meaning (green=healthy, yellow/red=
                  problems). All three levels now use --canvas-text-strong
                  (slate-600 light, purple-100 dark) for both stroke and
                  label so they read as quiet structural wrappers, not as
                  competing colored signals. Dashed-line cadence still
                  differentiates the three levels (env=4 3, sol=6 4, co=8 4). */}
              {envBounds.map((eb, i) => drawBox(
                eb.minX - pad.env, eb.minY - pad.env - labelH,
                (eb.maxX - eb.minX) + pad.env * 2, (eb.maxY - eb.minY) + pad.env * 2 + labelH,
                'var(--canvas-boundary-label)', '4 3', 0.35, 1, eb.label, formatCost(eb.cost_yearly_usd), 8
              ))}
              {Object.entries(solutions).map(([name, sol], i) => drawBox(
                sol.minX - pad.sol, sol.minY - pad.sol - labelH,
                (sol.maxX - sol.minX) + pad.sol * 2, (sol.maxY - sol.minY) + pad.sol * 2 + labelH,
                'var(--canvas-boundary-label)', '6 4', 0.35, 1.2, name, formatCost(sol.cost), 10
              ))}
              {drawBox(
                coMinX - pad.co, coMinY - pad.co - labelH,
                (coMaxX - coMinX) + pad.co * 2, (coMaxY - coMinY) + pad.co * 2 + labelH,
                'var(--canvas-boundary-label)', '8 4', 0.3, 1.5, `${company} — All Projects`, formatCost(totalCost), 12
              )}
            </g>
          )
        })()}

        {/* Encrypted infrastructure boundary — only shown when no manifest (discovery mode) */}
        {!isDemo && !manifestLayout && (() => {
          const pad = 85
          let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
          for (const nid of encryptedNodeIds) {
            const p = positions[nid]
            if (!p) continue
            if (p.x - pad < minX) minX = p.x - pad
            if (p.y - pad < minY) minY = p.y - pad
            if (p.x + pad > maxX) maxX = p.x + pad
            if (p.y + pad > maxY) maxY = p.y + pad
          }
          if (minX === Infinity) return null
          const zx = minX - 20, zy = minY - 30, zw = maxX - minX + 40, zh = maxY - minY + 55
          return (
            <g>
              <rect x={zx} y={zy} width={zw} height={zh} rx={16}
                fill="var(--group-fill-encrypted)" stroke={CV_ACCENT} strokeWidth={1.8}
                strokeDasharray="10 5" opacity={0.55} />
            </g>
          )
        })()}

        {/* HTTPS entry point indicator (live mode) */}
        {!isDemo && (() => {
          const frNode = nodes.find(n => n.id.startsWith('fr-'))
          if (!frNode) return null
          const frPos = positions[frNode.id]
          if (!frPos) return null
          return (
            <g>
              {/* REQ-005 + REQ-009 Phase 4b: HTTPS entry indicator via vars
                  so dark mode flips to purple-100/200 text on dark backdrop. */}
              <line x1={frPos.x - 90} y1={frPos.y} x2={frPos.x - 55} y2={frPos.y}
                stroke="var(--edge-deploy)" strokeWidth={1.2} markerEnd="url(#arrowhead)" opacity={0.7} />
              <text x={frPos.x - 95} y={frPos.y - 6} textAnchor="end"
                fill="var(--canvas-text-strong)" fontSize={9} fontWeight={600}>HTTPS</text>
              <text x={frPos.x - 95} y={frPos.y + 8} textAnchor="end"
                fill="var(--canvas-text-soft)" fontSize={7}>Internet</text>
            </g>
          )
        })()}

        {/* Group boxes (both modes — draggable, auto-expand) */}
        {/* VM group: click background (not inner nodes) to select ColdVault VM status */}
        {effectiveGroups.filter(g => g.label).map((g, idx) => (
          <g key={g.label || idx} style={{ cursor: 'grab' }}
            onMouseDown={(e) => onGroupMouseDown(e, g._idx)}
            onClick={() => {
              if (dragDist.current > 5) return
              // REQ-213: dynamic groups expose their parent manifest node id (e.g. pl-mig).
              // Clicking the group opens that parent's modal so MIG-level state is reachable.
              if (g.parent) {
                const mNode = manifestNodesById[g.parent]
                const topoNode = nodes.find(n => n.id === g.parent)
                if (mNode || topoNode) {
                  handleNodeClick(buildParentNodeRecord(g.parent, mNode, topoNode))
                  return
                }
              }
              if (!g.vmGroup) return
              // Select the project node in this group by nodeGroups membership
              const gIdx = g._idx
              const projNode = nodes.find(n => n.type === 'project' &&
                activeNodeGroups[n.id] === gIdx)
              if (projNode) handleNodeClick(projNode)
            }}>
            {/* REQ-005 + REQ-009 Phase 4b: group fills via CSS vars — each
                group-fill-* token has light + dark variants in index.css. */}
            <rect x={g.x} y={g.y} width={g.w} height={g.h} rx={12}
              fill={g.project ? 'var(--group-fill-project)'
                : g.partner ? 'var(--group-fill-partner)'
                : g.planned ? 'var(--group-fill-planned)'
                : (g.vmGroup || g.encrypted) ? 'var(--group-fill-encrypted)'
                : 'var(--group-fill-default)'}
              stroke={
                // REQ-217: partner groups (e.g. External LLM Providers) keep static color
                // regardless of child health — partners are independent, one failing model
                // shouldn't paint the whole group red.
                g.partner ? PARTNER_COLOR
                // REQ-008: when the group is healthy (or deployed), use a quiet slate
                // stroke instead of bright green so the canvas doesn't paint as a
                // uniform green wash. Non-healthy statuses keep the strong color so
                // degraded/error groups still stand out.
                // REQ-009 Phase 4b: var(--node-stroke-quiet) for healthy + slate fallback.
                : g._health && g._health !== 'healthy' && g._health !== 'deployed'
                    && STATUS_COLORS[g._health] ? STATUS_COLORS[g._health]
                : g._health && (g._health === 'healthy' || g._health === 'deployed') ? 'var(--node-stroke-quiet)'
                : g.project ? 'var(--canvas-accent-solution)'
                : g.planned ? PLANNED_COLOR
                : (g.vmGroup || g.encrypted) ? CV_ACCENT
                : 'var(--node-stroke-quiet)'}
              strokeWidth={(g.vmGroup || g.encrypted || g.partner || g.project) ? 1.2 : 1}
              // REQ-216: dynamic groups with a parent (clickable single element) render solid;
              // other encrypted/planned/project groups keep the dashed treatment.
              strokeDasharray={g.parent ? 'none' : g.encrypted ? '6 3' : g.planned ? '4 4' : g.project ? '5 3' : 'none'}
              opacity={g.planned ? 0.5 : g.project ? 0.8 : (g.vmGroup || g.encrypted) ? 0.7 : 1} />
            <text x={g.x + g.w / 2} y={g.y + 16} textAnchor="middle"
              fill={
                // REQ-217: partner label keeps static color for the same reason as the stroke.
                g.partner ? PARTNER_COLOR
                // REQ-008 + REQ-009 Phase 4b: healthy labels use --canvas-text-strong;
                // non-healthy use status color; project/encrypted use canvas accents.
                : g._health && g._health !== 'healthy' && g._health !== 'deployed'
                    && STATUS_COLORS[g._health] ? STATUS_COLORS[g._health]
                : g._health && (g._health === 'healthy' || g._health === 'deployed') ? 'var(--canvas-text-strong)'
                : g.project ? 'var(--canvas-accent-solution)'
                : g.planned ? PLANNED_COLOR
                : (g.vmGroup || g.encrypted) ? CV_ACCENT
                : 'var(--canvas-text-strong)'}
              fontSize={10} fontWeight={600}>{g.label}</text>
            {!hideCosts && g.cost_yearly_usd > 0 && (
              <text x={g.x + g.w - 8} y={g.y + 16} textAnchor="end"
                fill="var(--canvas-text-soft)" fontSize={8} fontFamily="monospace">
                {`$${g.cost_yearly_usd >= 1000
                  ? `${(g.cost_yearly_usd / 1000).toFixed(0)}k`
                  : g.cost_yearly_usd}/yr`}
              </text>
            )}
          </g>
        ))}

        {resolvedEdges.map((edge, i) => (
          <EdgeLine key={i} edge={edge} positions={resolvedPositions} index={i} />
        ))}

        {nodes.map((node, idx) => {
          const pos = positions[node.id]
          if (!pos) return null
          return (
            <TopologyNode
              key={node.id}
              node={hideCosts ? { ...node, cost_yearly_usd: null } : node}
              x={pos.x}
              y={pos.y}
              selected={selected === node.id}
              onClick={() => handleNodeClick(node)}
              onMouseDown={(e) => onNodeMouseDown(e, node.id)}
              onChildClick={(child) => handleNodeClick({
                ...child,
                source: 'manifest',
                _parentId: node.id,
                // REQ-212: child inherits parent's monitoring_logs when none declared
                // — logs visible for all nodes (e.g. Cloud Armor inherits LB's logs).
                monitoring_logs: child.monitoring?.logs || node.monitoring_logs || null,
                project_id: node.project_id || '',
                solution: node.solution || '',
                env: node.env || '',
              })}
            />
          )
        })}
      </svg>

      {/* Zoom controls — bottom center */}
      <div className="absolute bottom-3 left-1/2 -translate-x-1/2 flex gap-1">
        <button onClick={() => setViewBox(vb => {
          const nw = Math.max(400, vb.w * 0.8)
          const nh = Math.max(280, vb.h * 0.8)
          return { x: vb.x + (vb.w - nw) / 2, y: vb.y + (vb.h - nh) / 2, w: nw, h: nh }
        })} className="w-7 h-7 bg-surface/80 dark:bg-purple-800/80 border border-border dark:border-purple-700 rounded text-gray-600 dark:text-purple-200 hover:text-gray-900 dark:hover:text-white text-sm">+</button>
        <button onClick={() => setViewBox(vb => {
          const nw = Math.min(8000, vb.w * 1.2)
          const nh = Math.min(5200, vb.h * 1.2)
          return { x: vb.x - (nw - vb.w) / 2, y: vb.y - (nh - vb.h) / 2, w: nw, h: nh }
        })} className="w-7 h-7 bg-surface/80 dark:bg-purple-800/80 border border-border dark:border-purple-700 rounded text-gray-600 dark:text-purple-200 hover:text-gray-900 dark:hover:text-white text-sm">&ndash;</button>
        <button onClick={resetView}
          className="h-7 px-2 bg-surface/80 dark:bg-purple-800/80 border border-border dark:border-purple-700 rounded text-gray-600 dark:text-purple-200 hover:text-gray-900 dark:hover:text-white text-xs">Reset View</button>
        <button onClick={resetPositions}
          className="h-7 px-2 bg-surface/80 dark:bg-purple-800/80 border border-border dark:border-purple-700 rounded text-gray-600 dark:text-purple-200 hover:text-gray-900 dark:hover:text-white text-xs">Reset Layout</button>
      </div>
    </div>
  )
}
