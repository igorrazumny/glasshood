// File: frontend/src/components/ProjectTree.jsx
// Purpose: Left sidebar tree — hierarchical project navigation (All → Product → Env)
// Hide/pin behavior follows ColdVault sidebar pattern

import { useState, useRef, useEffect } from 'react'
import { ChevronRight, ChevronDown, Pin, PinOff, PanelLeftClose, PanelLeft } from 'lucide-react'
import PanelEdge from './PanelEdge'
import { PANEL_TOP } from '../utils/panels'
import { groupedCards } from '../utils/systems'

const STATUS_DOT = {
  healthy: 'bg-green-400',
  degraded: 'bg-yellow-400',
  error: 'bg-red-400',
  unknown: 'bg-gray-500',
  'not checked': 'bg-gray-400',
}

// Derive worst status from children (health rollup)
function worstStatus(statuses) {
  if (statuses.includes('error')) return 'error'
  if (statuses.includes('degraded')) return 'degraded'
  if (statuses.every(s => s === 'healthy')) return 'healthy'
  return 'unknown'
}

// Build tree: { product → { envs: [{ env, projectNode, status }], status } }
function buildTree(projectNodes) {
  const byProduct = {}
  for (const node of projectNodes) {
    const product = node.project || node.label || 'Unknown'
    if (!byProduct[product]) byProduct[product] = []
    byProduct[product].push(node)
  }

  return Object.entries(byProduct)
    .map(([product, nodes]) => {
      const envs = nodes.map(n => ({
        id: n.id,
        env: n.env || 'default',
        label: n.label,
        status: n.status || 'unknown',
        nodeCount: n.metrics?.node_count || 0,
        projectId: n.project_id || n.id,
      }))
      return {
        product,
        displayName: nodes[0]?.label?.replace(/\s*(Prod|Val|Dev|Staging)$/i, '').trim() || product,
        status: worstStatus(envs.map(e => e.status)),
        envs,
      }
    })
    .sort((a, b) => a.displayName.localeCompare(b.displayName))
}

function TreeItem({ label, status, active, onClick, indent = 0, count, bold }) {
  // REQ-009 round-7 sweep: light + dark: pairs. Active state uses
  // accent-500 (ColdVault medium blue brand accent) for the selected-item
  // tint and border. Inactive uses dark slate text on light bg, purple-100
  // on dark bg. `purple-*` here is the post-REQ-010 ColdVault BLUE scale
  // (not actual purple) — fine for the active state because brand-blue is
  // the right selected-item color across both themes.
  return (
    <button
      onClick={onClick}
      className={`w-full flex items-center gap-2.5 px-3 py-2 text-left text-[15px] transition-colors ${
        active
          ? 'bg-accent-500/15 text-accent-600 dark:text-accent-300 border-l-2 border-accent-500'
          : 'text-gray-700 dark:text-purple-200 hover:text-gray-900 dark:hover:text-purple-100 hover:bg-surface/50 dark:hover:bg-purple-700/30 border-l-2 border-transparent'
      } ${bold ? 'font-medium' : ''}`}
      style={{ paddingLeft: `${12 + indent * 14}px` }}
    >
      <span className={`w-2 h-2 rounded-full flex-shrink-0 ${STATUS_DOT[status] || STATUS_DOT.unknown}`} />
      <span className="truncate flex-1">{label}</span>
      {(typeof count === 'string' ? count : count > 0) && <span className="text-gray-500 dark:text-purple-300 text-xs">{count}</span>}
    </button>
  )
}

export default function ProjectTree({ projects, systems, activeProject, onSelect, open, pinned, onToggle, onPin, width, onResize }) {
  const [expanded, setExpanded] = useState({})
  const [resizing, setResizing] = useState(false)
  const [treeCollapsed, setTreeCollapsed] = useState(false)
  const ref = useRef(null)

  // Click outside closes unpinned sidebar
  useEffect(() => {
    if (!open || pinned) return
    const handler = (e) => {
      if (ref.current && !ref.current.contains(e.target)) {
        onToggle()
      }
    }
    document.addEventListener('pointerdown', handler)
    return () => document.removeEventListener('pointerdown', handler)
  }, [open, pinned, onToggle])

  if (!projects || projects.length === 0) return null

  const tree = buildTree(projects)
  const totalNodes = projects.reduce((sum, p) => sum + (p.metrics?.node_count || 0), 0)
  const overallStatus = worstStatus(projects.map(p => p.status || 'unknown'))

  // a group is open unless folded (false); one click folds, the next opens
  const toggleGroup = (id) => setExpanded(prev => ({ ...prev, [id]: prev[id] === false }))

  const toggleProduct = (product) => {
    setExpanded(prev => ({ ...prev, [product]: !prev[product] }))
  }

  return (
    <>
      {/* Hover trigger zone when sidebar is hidden */}
      {!open && (
        <div
          className="fixed left-0 w-4 z-40"
          style={{ top: PANEL_TOP, bottom: 0 }}
          onMouseEnter={onToggle}
        />
      )}

      {/* Toggle tab — flush against left window edge */}
      {!open && (
        <button
          onClick={onToggle}
          className="fixed left-0 z-50 w-7 py-3 bg-card dark:bg-purple-800 border-y border-r border-border dark:border-purple-700 rounded-r-lg shadow flex flex-col items-center gap-2 text-gray-600 hover:text-gray-900 dark:text-purple-200 dark:hover:text-white transition-colors"
          style={{ top: PANEL_TOP + 12 }}
          title="Show projects"
        >
          <PanelLeft size={16} />
          <span className="text-xs font-medium [writing-mode:vertical-rl] rotate-180">Projects</span>
        </button>
      )}

      {/* Sidebar panel */}
      <div
        ref={ref}
        className={`fixed left-0 z-40 bg-card dark:bg-purple-900 border-r border-border dark:border-purple-700 flex flex-col overflow-hidden rounded-r-lg ${
          resizing ? '' : 'transition-all duration-300'
        }`}
        style={{ top: PANEL_TOP, bottom: 0, width: open ? width : 0 }}
      >
        {open && <PanelEdge side="left" onResize={onResize} onResizing={setResizing} />}
        {/* Pin + hide controls — compact, no label */}
        <div className="flex items-center justify-end px-2 py-1.5 flex-shrink-0">
          <div className="flex items-center gap-1.5">
            <button
              onClick={onPin}
              className="text-gray-500 hover:text-gray-800 dark:text-purple-300 dark:hover:text-purple-100 transition-colors"
              title={pinned ? 'Unpin sidebar' : 'Pin sidebar'}
            >
              {pinned ? <Pin size={12} /> : <PinOff size={12} className="opacity-40 hover:opacity-100" />}
            </button>
            <button
              onClick={onToggle}
              className="flex items-center gap-1 px-1.5 py-0.5 rounded border border-border dark:border-purple-700 text-xs text-gray-600 hover:text-gray-900 hover:bg-surface dark:text-purple-200 dark:hover:text-white dark:hover:bg-purple-800 transition-colors"
              title="Hide projects"
            >
              <PanelLeftClose size={14} />
              Hide
            </button>
          </div>
        </div>

        {/* Tree content */}
        <div className="flex-1 overflow-y-auto py-1" style={{ width }}>
          {/* All Projects — collapsible root */}
          <div className="flex items-center">
            <button
              onClick={() => {
                setTreeCollapsed(v => {
                  if (!v) onSelect(null) // Reset filter when collapsing
                  return !v
                })
              }}
              className="pl-2 pr-1 py-2 text-gray-500 hover:text-gray-800 dark:text-purple-300 dark:hover:text-purple-100"
            >
              {treeCollapsed
                ? <ChevronRight size={14} />
                : <ChevronDown size={14} />}
            </button>
            <TreeItem
              label="All systems"
              status={overallStatus}
              active={activeProject === null}
              onClick={() => onSelect(null)}
              count={totalNodes}
              bold
            />
          </div>

          {/* REQ-GHA-035 clause 9 / REQ-GHA-037 clause 9: the two groups under All systems, each
              collapsible, small indents, the coloured dots say what needs attention */}
          {!treeCollapsed && systems?.length > 0 && groupedCards(systems).map(({ group, cards }) => {
            const worst = cards.some(c => c.state === 'error') ? 'error'
              : cards.some(c => c.state === 'degraded') ? 'degraded'
              : cards.every(c => c.state === 'healthy') ? 'healthy' : 'unknown'
            const folded = expanded[group.id] === false
            return (
              <div key={group.id}>
                <div className="flex items-center">
                  <button onClick={() => toggleGroup(group.id)} title={folded ? 'Show its systems' : 'Hide its systems'}
                    className="pl-4 pr-0.5 py-2 text-gray-500 hover:text-gray-800 dark:text-purple-300 dark:hover:text-purple-100">
                    {folded ? <ChevronRight size={13} /> : <ChevronDown size={13} />}
                  </button>
                  <TreeItem label={group.label} status={worst} active={activeProject === group.id}
                    onClick={() => onSelect(group.id)} indent={0} />
                </div>
                {!folded && cards.map(c => (
                  <TreeItem key={c.id} label={c.label} status={c.state} active={activeProject === c.id}
                    onClick={() => onSelect(c.id)} indent={3} />
                ))}
              </div>
            )
          })}

          {/* Product groups (collapsible under All Projects) — when no system cards are given */}
          {!treeCollapsed && !(systems?.length > 0) && tree.map(item => {
            const isExpanded = expanded[item.product] !== false // default expanded
            const hasMultipleEnvs = item.envs.length > 1
            return (
              <div key={item.product}>
                {/* Product row */}
                <div className="flex items-center">
                  {hasMultipleEnvs && (
                    <button
                      onClick={() => toggleProduct(item.product)}
                      className="pl-5 pr-1 py-2 text-gray-500 hover:text-gray-800 dark:text-purple-300 dark:hover:text-purple-100"
                    >
                      {isExpanded
                        ? <ChevronDown size={14} />
                        : <ChevronRight size={14} />}
                    </button>
                  )}
                  <TreeItem
                    label={item.displayName}
                    status={item.status}
                    active={false}
                    onClick={() => {
                      if (hasMultipleEnvs) {
                        toggleProduct(item.product)
                      } else {
                        onSelect(item.envs[0].id)
                      }
                    }}
                    indent={hasMultipleEnvs ? 0 : 2}
                    count={item.envs.reduce((s, e) => s + e.nodeCount, 0)}
                  />
                </div>

                {/* Environment children (only for multi-env products) */}
                {hasMultipleEnvs && isExpanded && item.envs.map(env => (
                  <TreeItem
                    key={env.id}
                    label={env.env}
                    status={env.status}
                    active={activeProject === env.id}
                    onClick={() => onSelect(env.id)}
                    indent={3}
                    count={env.nodeCount}
                  />
                ))}
              </div>
            )
          })}
        </div>
      </div>
    </>
  )
}
