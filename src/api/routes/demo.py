# File: src/api/routes/demo.py
# Purpose: Demo API routes — no authentication required
# Data lives in demo_data.py to keep this file small.

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter

from src.api.routes.demo_data import DEMO_TOPOLOGY, DEMO_ANALYSIS

router = APIRouter(tags=["demo"])


@router.get("/api/demo/topology")
async def demo_topology():
    """Static demo topology — no auth required."""
    return DEMO_TOPOLOGY


@router.get("/api/demo/analysis")
async def demo_analysis():
    """Static demo analysis — no auth required."""
    return DEMO_ANALYSIS


@router.get("/api/demo/logs/{node_id}")
async def demo_logs(node_id: str):
    """Sample log entries for demo mode — no auth required."""
    # Find the node's diagnostics text and format as log entries
    nodes = DEMO_TOPOLOGY.get("nodes", [])
    diag_text = ""
    for n in nodes:
        if n["id"] == node_id:
            diag_text = n.get("diagnostics", "")
            break

    if not diag_text:
        diag_text = f"[{node_id}] System operational. No recent events."

    # Format diagnostics lines as timestamped log entries
    now = datetime.now(timezone.utc)
    entries = []
    for i, line in enumerate(diag_text.strip().split("\n")):
        line = line.strip()
        if not line:
            continue
        ts = now - timedelta(minutes=len(diag_text.split("\n")) - i)
        severity = "ERROR" if "error" in line.lower() or "fail" in line.lower() else \
                   "WARNING" if "warn" in line.lower() or "degrad" in line.lower() or "throttl" in line.lower() else \
                   "INFO"
        entries.append({
            "timestamp": ts.isoformat(),
            "severity": severity,
            "message": line,
        })

    return {"node_id": node_id, "entries": entries, "count": len(entries)}
