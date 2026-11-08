// File: frontend/src/components/Dashboard.jsx
// Purpose: Main layout — header, topology, analysis, metrics bar
// Supports live mode (authenticated, polling) and demo mode (static data, no auth)

import { useState, useEffect, useCallback, useMemo } from 'react'
import StatusHeader from './StatusHeader'
import ProjectTree from './ProjectTree'
import RightSidebar from './RightSidebar'
import TopologyMap from './TopologyMap'
import AnalysisPanel from './AnalysisPanel'
import AlertPanel from './AlertPanel'
import SecurityPanel from './SecurityPanel'
import MetricsBar from './MetricsBar'
import NodeDetailModal from './NodeDetailModal'
import AlertDetailModal from './AlertDetailModal'
import VerificationReportModal from './VerificationReportModal'
import { usePolling } from '../hooks/usePolling'
import { computeManifestLayout } from '../utils/manifestLayout'
import { canvasNodes } from '../utils/canvasParts.js'
import { clearToken, apiFetch, apiUrl } from '../utils/api'
import { loadPanel, savePanel, fitPanels, landscapeInsets } from '../utils/panels'
import { systemCards, systemOfNodes, portfolioLine, systemId, isGroupId, cardsInGroup, headerLine, GROUPS, groupedCards, staleDataLine } from '../utils/systems'
import SystemsHome, { Waiting } from './SystemsHome'

function useDemoData() {
  const [topology, setTopology] = useState(null)
  const [analysis, setAnalysis] = useState(null)

  useEffect(() => {
    fetch(apiUrl('/api/demo/topology')).then(r => r.json()).then(setTopology)
    fetch(apiUrl('/api/demo/analysis')).then(r => r.json()).then(setAnalysis)
  }, [])

  return {
    topology: { data: topology, error: null, lastUpdated: Date.now(), refresh: () => {} },
    analysis: { data: analysis },
  }
}

export default function Dashboard({ onLogout, onSwitchToLive, mode = 'live' }) {
  const isDemo = mode === 'demo'
  // REQ-215: hide infrastructure costs only when the user is logged in via the
  // public-demo path (`?demo` → silent login as demo@glasshood.example.com).
  // Gating on the specific demo email avoids two problems with role-based detection:
  //   (1) race condition: Dashboard mounts before sessionStorage populates → defaults
  //       to 'viewer' → admin sees no costs;
  //   (2) Auth0 admins never populate sessionStorage.glasshood_creds, so a role-based
  //       gate would hide costs from them too.
  // Email-based gate is durable across both paths: only the demo session sets that
  // exact email, so admins (legacy or Auth0) and authenticated viewers always see costs.
  const hideCosts = (() => {
    try {
      const raw = sessionStorage.getItem('glasshood_creds')
      const creds = raw ? JSON.parse(raw) : null
      return creds?.login === 'demo@glasshood.example.com'
    } catch { return false }
  })()
  const [selectedNode, setSelectedNode] = useState(null)
  const [selectedAlert, setSelectedAlert] = useState(null)
  const [activeProject, setActiveProject] = useState(null)
  // REQ-GHA-033: each panel's open state and width are remembered in this browser
  const [sidebarOpen, setSidebarOpen] = useState(() => loadPanel('left').open)
  const [sidebarWidth, setSidebarWidth] = useState(() => loadPanel('left').width)
  const [sidebarPinned, setSidebarPinned] = useState(true)
  const [rightOpen, setRightOpen] = useState(() => loadPanel('right').open)
  const [rightWidth, setRightWidth] = useState(() => loadPanel('right').width)
  const [rightPinned, setRightPinned] = useState(true)
  const [viewport, setViewport] = useState(() => window.innerWidth)
  const [verifyReports, setVerifyReports] = useState(null)
  const [verifyLoading, setVerifyLoading] = useState(false)
  const [showVerifyModal, setShowVerifyModal] = useState(false)

  const liveTopology = usePolling(isDemo ? null : '/api/topology', 15000)
  const manifests = usePolling(isDemo ? null : '/api/manifests', 60000)
  const demo = useDemoData()

  const topology = isDemo ? demo.topology : liveTopology

  // Extract projects from manifest files (not org-discovery)
  const manifestData = Array.isArray(manifests?.data) ? manifests.data : []
  // REQ-GHA-036 clause 7: an external system's own AI overview when it is selected
  const selectedManifest = manifestData.find(m => systemId(m) === activeProject)
  // REQ-GHA-037: any selected system shows its own overview
  const analysisUrl = selectedManifest
    ? `/api/analysis?system=${encodeURIComponent(selectedManifest.product)}` : '/api/analysis'
  // REQ-GHA-037: each system's short AI assessment for its card
  const systemDescriptions = usePolling(isDemo ? null : '/api/analysis/systems', 60000)
  const liveAnalysis = usePolling(isDemo ? null : analysisUrl, 30000)
  const analysis = isDemo ? demo.analysis : liveAnalysis
  // REQ-GHA-023 clause 5: "nodes monitored" counts exactly what the canvas draws.
  const canvas = useMemo(() => (
    !isDemo && manifestData.length > 0 && topology.data
      ? canvasNodes(computeManifestLayout(topology.data?.nodes, manifestData), topology.data?.nodes)
      : null
  ), [isDemo, manifestData, topology.data])
  const manifestProjects = manifestData.filter(m => m && typeof m === 'object').map(m => ({
    id: `manifest-${m.product || 'unknown'}-${m.environment || 'unknown'}`,
    label: m.solution || m.display_name || m.product || 'Unknown',
    type: 'project',
    status: 'healthy',
    product: m.product || '',
    env: m.environment || '',
  }))
  // Deduplicate by solution name (show solution, not environment)
  const seen = new Set()
  const projectNodes = manifestProjects.filter(p => {
    const key = p.label
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })

  // Auto-logout when polling detects expired auth (401 → "Unauthorized")
  useEffect(() => {
    if (!isDemo && topology.error === 'Unauthorized') {
      clearToken()
      onLogout?.()
    }
  }, [topology.error, isDemo, onLogout])

  const currentUser = (() => {
    try {
      const raw = sessionStorage.getItem('glasshood_creds')
      return raw ? JSON.parse(raw).login || '' : ''
    } catch { return '' }
  })()

  const handleLogout = () => {
    clearToken()
    onLogout?.()
  }

  useEffect(() => { savePanel('left', { open: sidebarOpen, width: sidebarWidth }) }, [sidebarOpen, sidebarWidth])
  useEffect(() => { savePanel('right', { open: rightOpen, width: rightWidth }) }, [rightOpen, rightWidth])
  useEffect(() => {
    const onResize = () => setViewport(window.innerWidth)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])
  // Both widths are fitted together against the current window, so two open panels
  // always leave the landscape visible (also after the window shrinks)
  const fitted = fitPanels({
    left: { open: sidebarOpen && projectNodes.length > 0, width: sidebarWidth },
    right: { open: rightOpen, width: rightWidth },
  }, viewport)
  const leftWidth = fitted.left || sidebarWidth
  const rightPanelWidth = fitted.right || rightWidth

  const toggleSidebar = useCallback(() => setSidebarOpen(v => !v), [])
  const togglePin = useCallback(() => setSidebarPinned(v => !v), [])
  const toggleRight = useCallback(() => setRightOpen(v => !v), [])
  const toggleRightPin = useCallback(() => setRightPinned(v => !v), [])

  // REQ-603: Verification report
  const runVerification = useCallback(async () => {
    setVerifyLoading(true)
    setShowVerifyModal(true)
    try {
      const data = await apiFetch('/api/manifests/verify', { method: 'POST' })
      setVerifyReports(data.reports || [])
    } catch (e) {
      setVerifyReports([])
    }
    setVerifyLoading(false)
  }, [])

  // Dynamic padding for main content — both panels are fixed overlays
  // REQ-GHA-033 clause 3: the landscape uses exactly the space the panels leave free
  // On a phone the panels lie over the landscape (REQ-GHA-033 clause 6)
  const insets = landscapeInsets({
    left: sidebarOpen && sidebarPinned && projectNodes.length > 0 ? leftWidth : 0,
    right: rightOpen && rightPinned ? rightPanelWidth : 0,
  }, viewport)
  const leftShift = insets.left
  const rightShift = insets.right

  // REQ-GHA-035: each landscape file is one system; boxes carry their system (project/env)
  const allNodes = topology?.data?.nodes || []
  const owner = systemOfNodes(allNodes, manifestData)
  const cards = systemCards(manifestData, allNodes, topology?.data?.alerts)
  const systemLabel = new Map(cards.map(c => [c.id, c.label]))
  // REQ-GHA-035 clause 9: a group (9Robots or external systems) shows its systems' cards
  const groupSelected = isGroupId(activeProject)
  const selectedCard = cards.find(c => c.id === activeProject) || null
  const homeCards = cardsInGroup(cards, groupSelected ? activeProject : null)
  const showHome = !isDemo && cards.length > 1 && (activeProject === null || groupSelected)
  // Filter alerts/anomalies by the selected system or group
  const inScope = new Set(groupSelected ? homeCards.map(c => c.id) : activeProject ? [activeProject] : [])
  const contextNodeIds = activeProject
    ? new Set([...owner].filter(([, sys]) => inScope.has(sys)).map(([id]) => id))
    : null
  // The map of one selected system shows only that system
  const mapManifests = activeProject && !groupSelected ? manifestData.filter(m => systemId(m) === activeProject) : manifestData
  const mapData = activeProject && !groupSelected && topology.data && mapManifests.length
    ? { ...topology.data, nodes: allNodes.filter(n => owner.get(n.id) === activeProject || !owner.has(n.id)) }
    : topology.data
  const filteredAlerts = contextNodeIds
    ? (topology.data?.alerts || []).filter(a => contextNodeIds.has(a.node_id))
    : (topology.data?.alerts || [])
  const filteredResolved = contextNodeIds
    ? (topology.data?.resolved_alerts || []).filter(a => contextNodeIds.has(a.node_id))
    : (topology.data?.resolved_alerts || [])

  return (
    <div className="h-screen bg-surface dark:bg-purple-950 flex flex-col overflow-hidden">
      {isDemo && (
        <div className="bg-yellow-900/40 border-b border-yellow-700/50 px-4 py-2 flex items-center justify-between text-sm">
          <span className="text-yellow-300">Read-only · sample data (live system unavailable)</span>
          {onSwitchToLive && (
            <button onClick={onSwitchToLive} className="text-yellow-400 hover:text-yellow-300 text-xs">
              Switch to live system &rarr;
            </button>
          )}
        </div>
      )}
      <StatusHeader
        topology={topology.data}
        lastUpdated={topology.lastUpdated}
        onRefresh={topology.refresh}
        onLogout={isDemo ? null : handleLogout}
        isDemo={isDemo}
        readOnly={hideCosts && !isDemo}
        onVerify={isDemo ? null : runVerification}
        scope={isDemo ? null : !topology.data ? { text: 'Loading your systems…', state: 'unknown' }
          : cards.length > 1 ? headerLine(cards, activeProject) : null}
      />
      {projectNodes.length > 0 && (
        <ProjectTree
          projects={projectNodes}
          systems={cards}
          activeProject={activeProject}
          onSelect={setActiveProject}
          open={sidebarOpen}
          pinned={sidebarPinned}
          onToggle={toggleSidebar}
          onPin={togglePin}
          width={leftWidth}
          onResize={setSidebarWidth}
        />
      )}

      <RightSidebar open={rightOpen} pinned={rightPinned} onToggle={toggleRight} onPin={toggleRightPin}
        width={rightPanelWidth} onResize={setRightWidth}>
        {/* REQ-GHA-024 clause 1: the AI overview first; alerts and warnings are the detail below */}
        <div className="shrink-0">
          <AnalysisPanel data={analysis.data} topology={topology.data} canvas={canvas} isDemo={isDemo}
            loading={!analysis.data}
            scopeLabel={selectedCard ? selectedCard.label : groupSelected ? (GROUPS.find(g => g.id === activeProject)?.label || 'All monitored systems') : 'All monitored systems'}
            listCards={!isDemo && !selectedCard && (cards.length > 1 || !topology.data)
              ? groupedCards(homeCards).flatMap(g => g.cards) : null}
            descriptions={systemDescriptions.data || {}}
            fetchError={isDemo ? null : liveAnalysis.error}
            descriptionsError={isDemo ? null : systemDescriptions.error}
            systemsError={isDemo || topology.data ? null : topology.error}
            showStats={isDemo || !!selectedCard || cards.length <= 1} />
        </div>
        {/* REQ-GHA-027: an anomaly is an alarm on its part (with its classification in the
            detail), so it is not listed a second time in a separate anomaly panel */}
        <AlertPanel alerts={filteredAlerts} resolved={filteredResolved}
          systemOf={(!activeProject || groupSelected) && cards.length > 1 ? (a => systemLabel.get(owner.get(a.node_id)) || '') : null}
          rules={topology.data?.alarm_rules} onSelect={setSelectedAlert} />
        <div className="shrink-0">
          <SecurityPanel isDemo={isDemo} />
        </div>
      </RightSidebar>

      <div className="flex-1 overflow-hidden transition-all duration-300"
        style={{ paddingLeft: leftShift, paddingRight: rightShift, paddingTop: 8, paddingBottom: 8 }}>
        {!isDemo && topology.data && topology.error && topology.error !== 'Unauthorized' && (
          <div className="mx-2 mb-2 px-3 py-1.5 rounded border border-yellow-300 dark:border-yellow-400/30 bg-yellow-50 dark:bg-yellow-400/10 text-xs text-yellow-800 dark:text-yellow-300">
            {staleDataLine(topology.error, topology.lastUpdated)}
          </div>
        )}
        {!isDemo && !topology.data && !topology.error ? (
          <Waiting text="Loading your systems…" />
        ) : showHome ? (
          <SystemsHome cards={homeCards} line={portfolioLine(homeCards)} onOpen={setActiveProject}
            descriptions={systemDescriptions.data || {}} loading={!topology.data}
            loadError={topology.data ? null : topology.error}
            descriptionsError={systemDescriptions.error} />
        ) : (
          <TopologyMap key={activeProject || 'all'} data={mapData} error={topology.error} isDemo={isDemo} hideCosts={hideCosts}
            onNodeSelect={setSelectedNode} focusProjectId={mapManifests.length ? null : activeProject} manifests={mapManifests} />
        )}
      </div>

      <div className="transition-all duration-300" style={{ marginLeft: leftShift, marginRight: rightShift }}>
        <MetricsBar topology={topology.data} />
      </div>
      <NodeDetailModal node={selectedNode} onClose={() => setSelectedNode(null)} isDemo={isDemo} hideCosts={hideCosts} />
      {/* REQ-004: classification travels per-alert on selectedAlert.anomaly_classification —
          no global prop. AlertDetailModal reads its own alert's snapshot. */}
      <AlertDetailModal alert={selectedAlert} onClose={() => setSelectedAlert(null)} currentUser={currentUser} />
      {showVerifyModal && (
        <VerificationReportModal
          reports={verifyReports}
          loading={verifyLoading}
          onAccept={() => setShowVerifyModal(false)}
          onRecheck={runVerification}
          onClose={() => setShowVerifyModal(false)}
        />
      )}
    </div>
  )
}
