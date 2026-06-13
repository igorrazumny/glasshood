# File: src/api/routes/analysis.py
# Purpose: GET /api/analysis — AI analysis of infrastructure health via ColdVault API

from fastapi import APIRouter, HTTPException, Request

from src.api.routes.auth import verify_token
from src.api.routes.topology import get_topology_data
from src.analysis.coldvault_client import (
    get_analysis, analyze, can_refresh, analyze_node, refresh_node,
)

router = APIRouter(tags=["analysis"])


@router.get("/api/analysis")
def get_analysis_endpoint(request: Request):
    """Return cached ColdVault analysis. Requires auth token."""
    verify_token(request)
    return get_analysis()


@router.post("/api/analysis/refresh")
def refresh_analysis(request: Request):
    """Trigger manual analysis refresh. Rate limited to 1/min."""
    verify_token(request)

    if not can_refresh():
        raise HTTPException(status_code=429, detail="Rate limited. Try again in 60s.")

    topology = get_topology_data()
    result = analyze(topology)
    return result


@router.get("/api/analysis/node/{node_id}")
def get_node_analysis(node_id: str, request: Request):
    """Per-node AI analysis. Returns cached result instantly, refreshes in background if stale."""
    verify_token(request)

    topology = get_topology_data()
    node_data = next((n for n in topology.get("nodes", []) if n["id"] == node_id), None)
    if not node_data:
        raise HTTPException(status_code=404, detail=f"Node {node_id} not found")

    # Enrich node with compiled manifest data (metadata, logs, etc.)
    from src.manifest_compiler import compile_all
    from src.api.routes.manifests import _load_manifests
    compiled = compile_all(_load_manifests())
    for cm in compiled:
        for cn in cm.get("nodes", []):
            if cn.get("id") == node_id:
                # Merge compiled metadata into topology node
                for key in ("project_id", "project", "env", "environment",
                            "solution", "company", "gcp_resource_type"):
                    if cn.get(key):
                        node_data[key] = cn[key]
                break

    # Build connections from topology + manifest edges
    edges = topology.get("edges", [])
    connections = []
    for e in edges:
        if e.get("source") == node_id:
            connections.append(f"-> {e.get('target','?')}")
        elif e.get("target") == node_id:
            connections.append(f"<- {e.get('source','?')}")
    for cm in compiled:
        for edge in cm.get("edges", []):
            src, tgt = edge.get("source"), edge.get("target")
            label = edge.get("label", "")
            if src == node_id:
                connections.append(f"-> {tgt}" + (f" ({label})" if label else ""))
            elif tgt == node_id:
                connections.append(f"<- {src}" + (f" ({label})" if label else ""))
    connections = list(dict.fromkeys(connections))

    # Set last_checked from metrics cache
    from src.collectors.manifest_metrics import get_node_status
    cached = get_node_status(node_id)
    if cached and cached.get("last_poll"):
        from datetime import datetime, timezone
        node_data["last_checked"] = datetime.fromtimestamp(
            cached["last_poll"], tz=timezone.utc).isoformat()

    return analyze_node(node_data, connections)


@router.post("/api/analysis/node/{node_id}/refresh")
def refresh_node_analysis(node_id: str, request: Request):
    """Trigger manual refresh for a specific node. Non-blocking."""
    verify_token(request)

    topology = get_topology_data()
    node_data = next((n for n in topology.get("nodes", []) if n["id"] == node_id), None)
    if not node_data:
        raise HTTPException(status_code=404, detail=f"Node {node_id} not found")

    edges = topology.get("edges", [])
    connections = []
    for e in edges:
        if e["source"] == node_id:
            connections.append(f"-> {e['target']}")
        elif e["target"] == node_id:
            connections.append(f"<- {e['source']}")

    refresh_node(node_id, node_data, connections)
    return {"status": "refreshing", "node_id": node_id}
