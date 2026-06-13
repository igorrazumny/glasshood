# File: src/api/routes/report.py
# Purpose: GET /api/v1/report — machine-readable analysis for AI agents (Claude Code / 9r)

import hmac
import time
import logging

from fastapi import APIRouter, HTTPException, Request

from src.config.settings import GLASSHOOD_API_KEY
from src.api.routes.topology import get_topology_data
from src.analysis.coldvault_client import get_analysis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["report"])


def _verify_api_key(request: Request):
    """Verify API key from X-Api-Key header or Authorization Bearer."""
    if not GLASSHOOD_API_KEY:
        raise HTTPException(status_code=500, detail="GLASSHOOD_API_KEY not configured")

    api_key = request.headers.get("X-Api-Key", "")
    if not api_key:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            api_key = auth[7:]

    if not api_key or not hmac.compare_digest(api_key, GLASSHOOD_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid API key")


@router.get("/report")
def get_report(request: Request):
    """Full analysis + topology summary for AI agents.

    Auth: X-Api-Key header or Authorization: Bearer with GLASSHOOD_API_KEY.
    Returns cached data — no API calls triggered.
    """
    _verify_api_key(request)

    analysis = get_analysis()
    topology = get_topology_data()

    nodes = topology.get("nodes", [])

    status_counts = {"healthy": 0, "degraded": 0, "error": 0, "planned": 0, "other": 0}
    node_summaries = []
    for n in nodes:
        s = n.get("status", "unknown")
        if s in status_counts:
            status_counts[s] += 1
        else:
            status_counts["other"] += 1
        node_summaries.append({
            "id": n.get("id"),
            "type": n.get("type"),
            "label": n.get("label"),
            "status": s,
            "metrics": n.get("metrics", {}),
        })

    return {
        "timestamp": time.time(),
        "overall": {
            "score": analysis.get("score"),
            "summary": analysis.get("summary", ""),
            "issues": analysis.get("issues", []),
            "recommendations": analysis.get("recommendations", []),
            "stale": analysis.get("stale", True),
            "analysis_timestamp": analysis.get("timestamp"),
        },
        "nodes": node_summaries,
        "topology_summary": {
            "total_nodes": len(nodes),
            **status_counts,
        },
    }
