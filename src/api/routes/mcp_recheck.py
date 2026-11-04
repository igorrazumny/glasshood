# File: src/api/routes/mcp_recheck.py
# Purpose: POST /api/mcp-recheck/{node_id} — REQ-GHA-020 "Recheck via MCP".
# A logged-in operator (not Live demo, whose role is viewer) sends one question through
# the node's MCP `ask` tool. The server address comes only from the manifest. One
# recheck runs at a time, at most one per minute, so rechecks stay within ColdVault's
# per-caller limits. Nothing is stored; the answer text never leaves this module.

import threading
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.api.routes.auth import verify_token
from src.api.routes.manifests import _load_manifests
from src.auth.rbac import require_role
from src.collectors.coldvault_mcp import MODES, recheck_ask

router = APIRouter(tags=["mcp-recheck"])

MIN_INTERVAL_S = 60
_lock = threading.Lock()
_last_start = 0.0


class RecheckBody(BaseModel):
    mode: str = "vault"


def _recheck_url(node_id: str):
    for m in _load_manifests():
        for n in m.get("nodes", []):
            if n.get("id") == node_id:
                rc = (n.get("monitoring") or {}).get("recheck") or {}
                if rc.get("type") == "mcp_ask" and rc.get("url"):
                    return rc["url"]
    return None


@router.post("/api/mcp-recheck/{node_id}")
def mcp_recheck(node_id: str, request: Request, body: RecheckBody = RecheckBody()):
    global _last_start
    verify_token(request)
    require_role(request, "operator")
    if body.mode not in MODES:
        raise HTTPException(status_code=400, detail=f"mode must be one of {', '.join(MODES)}")
    url = _recheck_url(node_id)
    if not url:
        raise HTTPException(status_code=404, detail=f"Node {node_id} has no MCP recheck")
    if not _lock.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="A recheck is already running")
    try:
        wait = MIN_INTERVAL_S - (time.time() - _last_start)
        if wait > 0:
            raise HTTPException(status_code=429, detail=f"Next recheck possible in {int(wait) + 1}s")
        _last_start = time.time()
        return {"node_id": node_id, **recheck_ask(url, body.mode)}
    finally:
        _lock.release()
