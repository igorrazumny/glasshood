# File: src/api/routes/storage.py
# Purpose: Storage tier query and status endpoints

from fastapi import APIRouter, Request, Query
from typing import Optional

from src.api.routes.auth import verify_token
from src.auth.rbac import require_role, require_customer
from src.storage import pipeline, retention, query

router = APIRouter(tags=["storage"])


@router.get("/api/storage/events")
def storage_events(
    request: Request,
    source_id: Optional[str] = None,
    severity: Optional[str] = None,
    customer_id: Optional[str] = None,
    hours: int = Query(168, ge=1, le=8760),
    limit: int = Query(100, ge=1, le=10000),
):
    """Query events from hot/warm tiers (BigQuery). Requires operator role."""
    ctx = verify_token(request)
    require_role(request, "operator")
    # Customer isolation: scoped users can only query their own data
    user_cid = ctx.get("customer_id", "")
    if user_cid:
        customer_id = user_cid
    elif customer_id:
        require_customer(request, customer_id)
    events = query.query_hot(
        source_id=source_id, severity=severity, limit=limit, hours=hours,
        customer_id=customer_id,
    )
    return {"events": events, "count": len(events)}


@router.get("/api/storage/archives")
def storage_archives(
    request: Request,
    prefix: Optional[str] = None,
    customer_id: Optional[str] = None,
):
    """List cold tier archive files (GCS). Requires operator role."""
    ctx = verify_token(request)
    require_role(request, "operator")
    # Customer isolation
    user_cid = ctx.get("customer_id", "")
    if user_cid:
        customer_id = user_cid
    elif customer_id:
        require_customer(request, customer_id)
    archives = query.list_cold_archives(prefix=prefix, customer_id=customer_id or "")
    return {"archives": archives, "count": len(archives)}


@router.get("/api/storage/stats")
def storage_stats(request: Request):
    """Return storage pipeline and retention statistics."""
    verify_token(request)
    return {
        "pipeline": pipeline.get_stats(),
        "retention": retention.get_stats(),
    }
