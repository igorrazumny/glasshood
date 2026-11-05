# File: src/api/routes/analysis.py
# Purpose: REQ-GHA-024 — the AI overviews: system (top of the right panel) and per part.
# Overviews are written in the background (at start, then every 3 hours); these routes only
# read them. An operator may ask for a fresh system overview at most once every 10 minutes;
# a viewer (Live demo) sees the same overviews but cannot trigger one and does not see spend.

from fastapi import APIRouter, HTTPException, Request

from src.analysis import vertex_overview as ov
from src.api.routes.auth import verify_token
from src.api.routes.topology import get_topology_data
from src.auth.rbac import get_role_level

router = APIRouter(tags=["analysis"])


def _is_operator(request: Request) -> bool:
    ctx = getattr(request.state, "user_context", None) or {}
    return get_role_level(ctx.get("role", "")) >= get_role_level("operator")


@router.get("/api/analysis")
def get_analysis_endpoint(request: Request):
    verify_token(request)
    out = ov.get_system()
    if _is_operator(request):
        out["spend"] = ov.get_spend()
        out["refresh_in_s"] = ov.manual_refresh_allowed()
    return out


@router.post("/api/analysis/refresh")
def refresh_analysis(request: Request):
    verify_token(request)
    if not _is_operator(request):
        raise HTTPException(status_code=403, detail="Only an operator can ask for a fresh overview")
    wait = ov.manual_refresh_allowed()
    if wait:
        raise HTTPException(status_code=429, detail=f"Next fresh overview possible in {wait}s")
    ov.manual_refresh(get_topology_data())
    return ov.get_system()


@router.get("/api/analysis/node/{node_id}")
def get_node_analysis(node_id: str, request: Request):
    verify_token(request)
    entry = ov.get_part(node_id)
    if entry is None:
        return {"score": None, "summary": "", "issues": [], "recommendations": [],
                "analyzed_at": None, "stale": True, "model": ov.MODEL,
                "error": "No overview for this part yet — written at start and every 3 hours"}
    return entry
