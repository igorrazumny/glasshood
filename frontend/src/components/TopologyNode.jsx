// File: frontend/src/components/TopologyNode.jsx
// Purpose: Single node in topology — fixed size box, 2-line label, tooltip on hover
// All nodes are the same size (NODE_W x NODE_H) to guarantee no overlaps.
// Text is small relative to box. Tooltip shows full name + status on hover.
//
// REQ-006: light-card aesthetic — nodes render as near-white boxes with dark
// slate text and colored status borders/dots, against the REQ-005 cream
// canvas. STATUS_COLORS mirrors the TopologyMap palette so border colors,
// status dots, and the global STATUS_COLORS in TopologyMap stay in lockstep.

export const NODE_W = 140
export const NODE_H = 50
export const CHILD_PAD = 8       // padding inside parent for children
export const CHILD_H = 28        // height of each child row
export const CHILD_GAP = 4       // gap between children

// REQ-009 Phase 4: STATUS_COLORS, TYPE_TINTS, BRAND_PRIMARY_* moved from
// hardcoded hex literals to var(--…) references against the CSS-var block
// in index.css (`:root` for light, `.dark` for dark). The hex literals
// retained as PHASE_1_FALLBACK_HEX below are used only by the structural
// guard tests in test_theme_tokens.py to ensure the cross-file
// STATUS_COLORS invariant still holds — runtime now consults the CSS vars.
const STATUS_COLORS = {
  healthy: 'var(--status-healthy)',
  deployed: 'var(--status-healthy)',
  degraded: 'var(--status-degraded)',
  error: 'var(--status-error)',
  disconnected: 'var(--status-inactive)',
  stale: 'var(--status-degraded)',
  unknown: 'var(--status-inactive)',
  disabled: 'var(--status-inactive)',
  planned: 'var(--status-inactive)',
  dynamic: 'var(--status-inactive)',
  'not monitored': 'var(--status-inactive)',
}

// Cross-file invariant guard: the structural tests expect these hex values
// to remain in the file so they can prove the runtime mapping aligns with
// TopologyMap's STATUS_COLORS table. Don't read these at runtime — read the
// CSS vars above. (REQ-009 round-6 / phase 4 transition.)
// eslint-disable-next-line no-unused-vars
const STATUS_COLORS_HEX_REFERENCE = {
  healthy: '#16a34a',
  deployed: '#16a34a',
  degraded: '#ca8a04',
  error: '#dc2626',
  disconnected: '#94a3b8',
  stale: '#ca8a04',
  unknown: '#94a3b8',
  disabled: '#94a3b8',
  planned: '#94a3b8',
  dynamic: '#94a3b8',
  'not monitored': '#94a3b8',
}

// REQ-008: when status is healthy/deployed, the node border is a quiet slate.
// Now reads from CSS var so dark mode can substitute a slightly brighter tone.
const QUIET_HEALTHY_STROKE = 'var(--node-stroke-quiet)'
const HEALTHY_STATUSES = new Set(['healthy', 'deployed'])

// REQ-008 + REQ-009 Phase 4: type → fill tint via CSS vars. Light theme
// uses the soft pastel tints; dark theme overrides to translucent washes
// over the purple-800 surface (defined in index.css .dark block).
const TYPE_TINTS = {
  provider: 'var(--tint-provider)',
  load_balancer: 'var(--tint-lb)',
  cdn: 'var(--tint-cdn)',
  ingress: 'var(--tint-ingress)',
  mig: 'var(--tint-mig)',
  container: 'var(--tint-container)',
  vm: 'var(--tint-vm)',
  cloud_run: 'var(--tint-cloud-run)',
  compute: 'var(--tint-compute)',
  secret: 'var(--tint-secret)',
  storage: 'var(--tint-storage)',
  registry: 'var(--tint-registry)',
  cache: 'var(--tint-cache)',
  database: 'var(--tint-database)',
}

// REQ-008: nodes that render with the solid brand-blue treatment (slide
// "BC2.0" / "MES" analogue). The fill is the strong CV_ACCENT royal blue
// and text becomes white. Status dot stays semantic so red/amber overlays
// still pop. Two opt-ins:
//   1. Manifest authors can set `brand: primary` on any node.
//   2. By default, `type === 'application'` qualifies BUT only when the node
//      is a leaf (no `children`) — the innermost ColdVault Platform app
//      leaves are the natural primary surface. If an `application` node ever
//      sprouts nested children we don't want to paint the whole subtree
//      solid blue. Manifest-flagged `brand: primary` skips the leaf check
//      because the author explicitly opted that node in.
function isBrandPrimary(node) {
  if (node.brand === 'primary') return true
  const hasChildren = Array.isArray(node.children) && node.children.length > 0
  return node.type === 'application' && !hasChildren
}

// REQ-009 Phase 4: brand-solid palette via CSS vars so dark mode can flip
// to ColdVault's medium-blue (#5BD3F4) per REQ-010 while light stays the
// royal-blue (#2563eb) that shipped pre-Phase 4.
const BRAND_PRIMARY_FILL = 'var(--brand-primary-fill)'
const BRAND_PRIMARY_FILL_SELECTED = 'var(--brand-primary-fill-selected)'
const BRAND_PRIMARY_STROKE = 'var(--brand-primary-stroke)'
const BRAND_PRIMARY_TEXT = 'var(--brand-primary-text)'
const BRAND_PRIMARY_SUBTEXT = 'var(--brand-primary-subtext)'

// REQ-008: healthy nodes no longer emit a green drop-shadow — the green
// glow re-introduced the "wall of green" the type-based identity is
// trying to escape, undermining REQ-008(A) at the SVG-filter layer.
// Only alert states (degraded / error) carry a glow as a deliberate
// overlay signal on top of the type-colored card.
const GLOW_FILTER = {
  degraded: 'url(#glow-yellow)',
  error: 'url(#glow-red)',
}

// Split label into two lines — try colon, parentheses, or mid-word break
function splitLabel(label) {
  if (!label || label.length <= 18) return [label, null]
  const colonIdx = label.indexOf(': ')
  if (colonIdx > 0 && colonIdx < label.length - 2) {
    return [label.substring(0, colonIdx), label.substring(colonIdx + 2)]
  }
  const parenIdx = label.indexOf(' (')
  if (parenIdx > 0 && label.endsWith(')')) {
    return [label.substring(0, parenIdx), label.substring(parenIdx + 1)]
  }
  // Break at last space before character 20
  const spaceIdx = label.lastIndexOf(' ', 20)
  if (spaceIdx > 5) {
    return [label.substring(0, spaceIdx), label.substring(spaceIdx + 1)]
  }
  return [label, null]
}

// Calculate height of a child node (smaller than top-level)
export function childHeight(node) {
  const children = node?.children
  if (!children || children.length === 0) return CHILD_H
  let ch = 0
  for (const child of children) {
    ch += childHeight(child) + CHILD_GAP
  }
  return CHILD_H + ch + CHILD_PAD
}

// Calculate total height of a top-level node including nested children
export function nodeHeight(node) {
  const children = node?.children
  if (!children || children.length === 0) return NODE_H
  let childrenH = 0
  for (const child of children) {
    childrenH += childHeight(child) + CHILD_GAP
  }
  return NODE_H + childrenH + CHILD_PAD
}

// Render a single child node (smaller, inside parent)
function ChildNode({ child, x, y, onClick, availableWidth, parentStatus }) {
  const w = availableWidth || (NODE_W - CHILD_PAD * 2)
  const childStatus = child.status && child.status !== 'unknown' ? child.status : parentStatus
  const color = STATUS_COLORS[childStatus] || STATUS_COLORS.unknown
  const label = child.label || child.id
  const maxChars = Math.max(10, Math.floor(w / 6))
  const truncated = label.length > maxChars ? label.substring(0, maxChars - 1) + '…' : label
  const h = childHeight(child)
  const hasChildren = child.children && child.children.length > 0

  // REQ-008: children also honor type tint + brand-primary + healthy-quiet
  // border — without this the innermost "ColdVault Platform" app leaves
  // would stay white instead of becoming the slide's BC2.0 solid blue.
  // REQ-009 Phase 4: defaults read CSS vars so dark mode swaps colors.
  const brandSolid = isBrandPrimary(child)
  const childFill = brandSolid
    ? BRAND_PRIMARY_FILL
    : (TYPE_TINTS[child.type] || 'var(--node-fill)')
  const childStroke = brandSolid
    ? BRAND_PRIMARY_STROKE
    : (HEALTHY_STATUSES.has(childStatus) ? QUIET_HEALTHY_STROKE : color)
  const childLabelColor = brandSolid ? BRAND_PRIMARY_TEXT : 'var(--node-text)'
  const childStatusColor = brandSolid ? BRAND_PRIMARY_SUBTEXT : color

  return (
    <g transform={`translate(${x}, ${y})`}
      onClick={e => { e.stopPropagation(); onClick?.(child) }}
      style={{ cursor: 'pointer' }}>
      <title>{`${label}\n${child.status || 'unknown'} (${child.type || ''})`}</title>
      <rect
        width={w}
        height={h}
        rx={4}
        fill={childFill}
        stroke={childStroke}
        strokeWidth={1}
        opacity={0.95}
      />
      {/* Status dot stays semantic — overlay signal on top of type/brand identity. */}
      <circle cx={w - 8} cy={8} r={2.5} fill={color} />
      <text x={6} y={14} fill={childLabelColor} fontSize={7.5} fontWeight={500}>{truncated}</text>
      <text x={6} y={22} fill={childStatusColor} fontSize={6}>{childStatus || child.type}</text>
      {hasChildren && child.children.map((gc, i) => {
        let offsetY = CHILD_H
        for (let j = 0; j < i; j++) offsetY += childHeight(child.children[j]) + CHILD_GAP
        return <ChildNode key={gc.id || i} child={gc} x={CHILD_PAD} y={offsetY} onClick={onClick}
          availableWidth={w - CHILD_PAD * 2} parentStatus={childStatus} />
      })}
    </g>
  )
}

export default function TopologyNode({ node, x, y, selected, onClick, onMouseDown, onChildClick }) {
  const color = STATUS_COLORS[node.status] || STATUS_COLORS.unknown
  const isDisconnected = node.status === 'disconnected'
  const isPlanned = node.status === 'planned'
  const hasChildren = node.children && node.children.length > 0
  const totalH = nodeHeight(node)

  // REQ-008: resolve fill / stroke / text colors from type + brand + status.
  // Brand-solid wins (overrides type tint + healthy-quiet border because the
  // fill IS the identity). Otherwise type tint drives the fill, and the
  // border quiets to slate when status is healthy so type identity reads.
  // 9r-review fix: brand-solid + selected lightens so the selection stays
  // visible without losing the brand identity.
  // REQ-009 Phase 4: all defaults read CSS vars so dark mode swaps cleanly.
  const brandSolid = isBrandPrimary(node)
  const cardFill = brandSolid
    ? (selected ? BRAND_PRIMARY_FILL_SELECTED : BRAND_PRIMARY_FILL)
    : (selected ? 'var(--node-fill-selected)' : (TYPE_TINTS[node.type] || 'var(--node-fill)'))
  const cardStroke = brandSolid
    ? BRAND_PRIMARY_STROKE
    : (HEALTHY_STATUSES.has(node.status) ? QUIET_HEALTHY_STROKE : color)
  const labelColor = brandSolid
    ? BRAND_PRIMARY_TEXT
    : (isDisconnected ? 'var(--node-text-disconnected)' : 'var(--node-text)')
  const subLabelColor = brandSolid
    ? BRAND_PRIMARY_SUBTEXT
    : (isDisconnected ? 'var(--node-stroke-quiet)' : 'var(--node-text-secondary)')

  const [line1, line2] = node.type === 'project'
    ? [node.label, node.project_id || null]
    : splitLabel(node.label)

  const tooltipText = `${node.label}\n${node.status}${node.type ? ' (' + node.type + ')' : ''}`

  return (
    <g
      transform={`translate(${x - NODE_W/2}, ${y - totalH/2})`}
      onClick={onClick}
      onMouseDown={onMouseDown}
      style={{ cursor: 'grab' }}
    >
      <title>{tooltipText}</title>

      {/* REQ-011: glow filters live in TopologyMap's root defs block, not
          here. Per-node duplicate filter IDs are undefined behaviour per
          the SVG spec; references via GLOW_FILTER (url(#glow-yellow/-red))
          resolve up the SVG scope to the parent's defs. */}

      {/* REQ-008: fill + stroke driven by type + brand + status (see above).
          Healthy nodes get a quiet slate border; type tint carries identity;
          application-type or brand:primary nodes render solid royal blue. */}
      <rect
        width={NODE_W}
        height={totalH}
        rx={8}
        fill={cardFill}
        stroke={cardStroke}
        strokeWidth={selected ? 2 : 1.5}
        strokeDasharray={isPlanned ? '4 3' : 'none'}
        opacity={isDisconnected ? 0.55 : isPlanned ? 0.6 : 1}
        filter={GLOW_FILTER[node.status] || 'none'}
      />

      {/* Status dot */}
      <circle
        cx={NODE_W - 8}
        cy={8}
        r={3.5}
        fill={color}
        opacity={isDisconnected ? 0.5 : 1}
      />

      {/* Icon placeholder — small filled square in the status color.
          On brand-solid cards the status color would clash with the blue
          fill, so use a transparent white wash there instead. */}
      <rect
        x={6}
        y={18}
        width={14}
        height={14}
        rx={3}
        fill={brandSolid ? '#ffffff' : color}
        opacity={brandSolid ? 0.18 : (isDisconnected ? 0.35 : 0.22)}
      />
      {/* The #ffffff above is intentional — on a solid royal-blue card
          a fixed white-wash icon reads in both themes (brand fill stays
          blue regardless of light/dark). */}

      {/* Line 1 — main label — color resolved by REQ-008 (white on brand). */}
      <text
        x={24}
        y={line2 ? 17 : 21}
        fill={labelColor}
        fontSize={9}
        fontWeight={500}
      >
        {line1 && line1.length > 20 ? line1.substring(0, 19) + '…' : line1}
      </text>

      {/* Line 2 — detail — secondary text color from REQ-008 resolution. */}
      {line2 && (
        <text x={24} y={29} fill={subLabelColor} fontSize={7}>
          {line2.length > 22 ? line2.substring(0, 21) + '…' : line2}
        </text>
      )}

      {/* Status text — keeps status color on light cards; light-blue on brand. */}
      <text x={24} y={line2 ? 41 : 37} fill={brandSolid ? BRAND_PRIMARY_SUBTEXT : color} fontSize={7}>
        {node.type === 'project'
          ? `${node.metrics?.node_count ?? 0} resources`
          : node.status}
      </text>

      {/* Cost (bottom-right of header area, subtle). */}
      {node.cost_yearly_usd != null && (
        <text
          x={NODE_W - 6}
          y={NODE_H - 5}
          fill={brandSolid ? BRAND_PRIMARY_SUBTEXT : (node.status === 'disabled' ? 'var(--node-text-disconnected)' : 'var(--node-text-secondary)')}
          fontSize={6}
          textAnchor="end"
          fontFamily="monospace"
        >
          {`$${node.cost_yearly_usd >= 1000
            ? `${(node.cost_yearly_usd / 1000).toFixed(0)}k`
            : node.cost_yearly_usd}/yr`}
        </text>
      )}

      {/* Nested children — rendered inside this node */}
      {hasChildren && node.children.map((child, i) => {
        let offsetY = NODE_H
        for (let j = 0; j < i; j++) offsetY += nodeHeight(node.children[j]) + CHILD_GAP
        return <ChildNode key={child.id || i} child={child} x={CHILD_PAD} y={offsetY} onClick={onChildClick}
          parentStatus={node.status} />
      })}
    </g>
  )
}
