// File: frontend/src/components/Dashboard.jsx
// Purpose: Main layout — header, topology, analysis, metrics bar
// Supports live mode (authenticated, polling) and demo mode (static data, no auth)

import { useState, useEffect, useCallback } from 'react'
import StatusHeader from './StatusHeader'
import ProjectTree from './ProjectTree'
import RightSidebar from './RightSidebar'
import TopologyMap from './TopologyMap'
import AnalysisPanel from './AnalysisPanel'
import AlertPanel from './AlertPanel'
import SecurityPanel from './SecurityPanel'
import AnomalyBadge from './AnomalyBadge'
import MetricsBar from './MetricsBar'
import NodeDetailModal from './NodeDetailModal'
import AlertDetailModal from './AlertDetailModal'
import AnomalyDetailModal from './AnomalyDetailModal'
import VerificationReportModal from './VerificationReportModal'
import { usePolling } from '../hooks/usePolling'
import { clearToken, apiFetch } from '../utils/api'

function useDemoData() {
  const [topology, setTopology] = useState(null)
  const [analysis, setAnalysis] = useState(null)

  useEffect(() => {
    fetch('/api/demo/topology').then(r => r.json()).then(setTopology)
    fetch('/api/demo/analysis').then(r => r.json()).then(setAnalysis)
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
  const [selectedAnomaly, setSelectedAnomaly] = useState(null)
  const [activeProject, setActiveProject] = useState(null)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [sidebarPinned, setSidebarPinned] = useState(true)
  const [rightOpen, setRightOpen] = useState(true)
  const [rightPinned, setRightPinned] = useState(true)
  const [verifyReports, setVerifyReports] = useState(null)
  const [verifyLoading, setVerifyLoading] = useState(false)
  const [showVerifyModal, setShowVerifyModal] = useState(false)

  const liveTopology = usePolling(isDemo ? null : '/api/topology', 15000)
  const liveAnalysis = usePolling(isDemo ? null : '/api/analysis', 30000)
  const manifests = usePolling(isDemo ? null : '/api/manifests', 60000)
  const demo = useDemoData()

  const topology = isDemo ? demo.topology : liveTopology
  const analysis = isDemo ? demo.analysis : liveAnalysis

  // Extract projects from manifest files (not org-discovery)
  const manifestData = Array.isArray(manifests?.data) ? manifests.data : []
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
  const leftShift = sidebarOpen && sidebarPinned && projectNodes.length > 0 ? 248 : 8
  const rightShift = rightOpen && rightPinned ? 328 : 8

  // Filter alerts/anomalies by selected project context
  const selectedProject = activeProject ? projectNodes.find(p => p.id === activeProject) : null
  const contextNodeIds = (() => {
    if (!selectedProject) return null
    const product = selectedProject.project || ''
    const env = selectedProject.env || ''
    const allNodes = topology?.data?.nodes || []
    return new Set(
      allNodes
        .filter(n => n.project === product && (!env || !n.env || n.env === env))
        .map(n => n.id)
    )
  })()
  const filteredAlerts = contextNodeIds
    ? (topology.data?.alerts || []).filter(a => contextNodeIds.has(a.node_id))
    : (topology.data?.alerts || [])
  const filteredAnomalies = contextNodeIds
    ? (topology.data?.anomalies || []).filter(a => contextNodeIds.has(a.node_id))
    : (topology.data?.anomalies || [])

  return (
    <div className="h-screen bg-surface dark:bg-purple-950 flex flex-col overflow-hidden">
      {isDemo && (
        <div className="bg-yellow-900/40 border-b border-yellow-700/50 px-4 py-2 flex items-center justify-between text-sm">
          <span className="text-yellow-300">DEMO — viewing sample data</span>
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
        onVerify={isDemo ? null : runVerification}
      />
      {projectNodes.length > 0 && (
        <ProjectTree
          projects={projectNodes}
          activeProject={activeProject}
          onSelect={setActiveProject}
          open={sidebarOpen}
          pinned={sidebarPinned}
          onToggle={toggleSidebar}
          onPin={togglePin}
        />
      )}

      <RightSidebar open={rightOpen} pinned={rightPinned} onToggle={toggleRight} onPin={toggleRightPin}>
        <AlertPanel alerts={filteredAlerts} onSelect={setSelectedAlert} />
        <AnomalyBadge anomalies={filteredAnomalies} onSelect={setSelectedAnomaly} />
        <SecurityPanel isDemo={isDemo} />
        <AnalysisPanel data={analysis.data} topology={topology.data} isDemo={isDemo} />
      </RightSidebar>

      <div className="flex-1 overflow-hidden transition-all duration-300"
        style={{ paddingLeft: leftShift, paddingRight: rightShift, paddingTop: 8, paddingBottom: 8 }}>
        <TopologyMap data={topology.data} error={topology.error} isDemo={isDemo} hideCosts={hideCosts} onNodeSelect={setSelectedNode} focusProjectId={activeProject} manifests={manifestData} />
      </div>

      <div className="transition-all duration-300" style={{ marginLeft: leftShift, marginRight: rightShift }}>
        <MetricsBar topology={topology.data} />
      </div>
      <NodeDetailModal node={selectedNode} onClose={() => setSelectedNode(null)} isDemo={isDemo} hideCosts={hideCosts} />
      {/* REQ-004: classification travels per-alert on selectedAlert.anomaly_classification —
          no global prop. AlertDetailModal reads its own alert's snapshot. */}
      <AlertDetailModal alert={selectedAlert} onClose={() => setSelectedAlert(null)} currentUser={currentUser} />
      <AnomalyDetailModal anomaly={selectedAnomaly} onClose={() => setSelectedAnomaly(null)} />
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
