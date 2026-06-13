# File: src/api/routes/integrations.py
# Purpose: ServiceNow integration management API

from fastapi import APIRouter, Request, HTTPException

from src.api.routes.auth import verify_token
from src.integrations.sync import (
    get_correlation_results, get_sync_state, sync_once, get_audit_log,
)
from src.config.settings import SNOW_ENABLED

router = APIRouter(tags=["integrations"])


@router.get("/api/integrations/snow/status")
def snow_status(request: Request):
    """Return ServiceNow integration health."""
    verify_token(request)
    results = get_correlation_results()
    return {
        "enabled": SNOW_ENABLED,
        "sync_state_count": len(get_sync_state()),
        "correlations": (len(results.get("incident_correlations", []))
                         + len(results.get("change_correlations", []))),
        "patterns": len(results.get("patterns", [])),
        "last_sync": results.get("timestamp"),
    }


@router.get("/api/integrations/snow/correlations")
def snow_correlations(request: Request):
    """Return current SNOW ticket correlations (incidents + changes)."""
    verify_token(request)
    results = get_correlation_results()
    return {
        "incident_correlations": results.get("incident_correlations", []),
        "change_correlations": results.get("change_correlations", []),
        "total": (len(results.get("incident_correlations", []))
                  + len(results.get("change_correlations", []))),
        "timestamp": results.get("timestamp"),
    }


@router.get("/api/integrations/snow/patterns")
def snow_patterns(request: Request):
    """Return surfaced cross-system patterns."""
    verify_token(request)
    results = get_correlation_results()
    return {
        "patterns": results.get("patterns", []),
        "count": len(results.get("patterns", [])),
        "timestamp": results.get("timestamp"),
    }


@router.get("/api/integrations/snow/sync-state")
def snow_sync_state(request: Request):
    """Return which GlassHood alerts have SNOW incidents."""
    verify_token(request)
    state = get_sync_state()
    return {"synced_alerts": state, "count": len(state)}


@router.post("/api/integrations/snow/sync")
def manual_sync(request: Request):
    """Trigger an immediate SNOW sync cycle."""
    verify_token(request)
    if not SNOW_ENABLED:
        raise HTTPException(status_code=503,
                            detail="ServiceNow integration not enabled")
    sync_once()
    return {"status": "sync_complete", "sync_state_count": len(get_sync_state())}
