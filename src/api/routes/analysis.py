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
def get_analysis_endpoint(request: Request, system: str = None):
    verify_token(request)
    # REQ-GHA-036 clause 7: an external system's own overview when it is selected; never
    # another system's overview in its place
    if system:
        from src.api.routes.manifests import _load_manifests
        kinds = {m.get("product"): m.get("kind") for m in _load_manifests()}
        if system not in kinds:
            raise HTTPException(status_code=404, detail=f"Unknown system {system!r}")
        not_yet = {"score": None, "summary": "", "issues": [], "recommendations": [], "analyzed_at": None,
                   "stale": True, "error": "The AI evaluation of this system has not run yet"}
        if kinds[system] == "outside_view":
            out = ov.get_outside(system) or not_yet
        else:
            out = ov.get_own(system) or not_yet   # REQ-GHA-037: this system's own overview
    else:
        out = ov.get_system()
    out["ai_offline"] = ov.ai_offline()
    if _is_operator(request):
        out["spend"] = ov.get_spend()
        out["refresh_in_s"] = ov.manual_refresh_allowed()
    return out


@router.get("/api/analysis/selections")
def get_selection_reviews(request: Request):
    """REQ-GHA-046: the short review of all systems and of each group."""
    verify_token(request)
    from src.analysis import selection_review
    return selection_review.get_reviews()


@router.get("/api/analysis/systems")
def get_system_cards(request: Request):
    """REQ-GHA-037: each system's short AI description, for the home view's cards."""
    verify_token(request)
    return ov.system_cards()


@router.post("/api/analysis/refresh")
def refresh_analysis(request: Request):
    verify_token(request)
    if not _is_operator(request):
        raise HTTPException(status_code=403, detail="Only an operator can ask for a fresh overview")
    wait = ov.reserve_manual_refresh()  # check and take the slot in one step, before any work
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
                "error": "No evaluation of this part yet — it runs at start and every 3 hours"}
    return entry
