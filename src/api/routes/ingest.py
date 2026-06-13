# File: src/api/routes/ingest.py
# Purpose: Backend ingestion endpoints for remote agent events

from fastapi import APIRouter, Request, Query
from pydantic import BaseModel
from typing import Optional

from src.api.routes.auth import verify_token
from src.auth.rbac import require_role, require_customer
from src.ingest import processor

router = APIRouter(tags=["ingest"])


class IngestBatch(BaseModel):
    agent_id: str
    customer_id: str = ""
    events: list[dict]


@router.post("/api/ingest/events")
def ingest_events(request: Request, body: IngestBatch):
    """Receive a batch of events from a remote agent."""
    ctx = verify_token(request)
    require_role(request, "operator")
    if len(body.events) > 500:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Batch too large (max 500)")
    # Enforce customer isolation: scoped users can only ingest for their customer
    user_cid = ctx.get("customer_id", "")
    if user_cid:
        body.customer_id = user_cid  # Override with auth-scoped customer
    elif body.customer_id:
        require_customer(request, body.customer_id)
    # Inject customer_id into each event for storage pipeline
    if body.customer_id:
        for event in body.events:
            event.setdefault("customer_id", body.customer_id)
    result = processor.process_batch(body.events, body.agent_id)
    return result


@router.post("/api/ingest/heartbeat")
def ingest_heartbeat(request: Request, body: dict):
    """Receive heartbeat from a remote agent."""
    verify_token(request)
    agent_id = body.get("agent_id", "")
    if agent_id:
        processor.record_heartbeat(agent_id, body)
    return {"status": "ok"}


@router.get("/api/ingest/status")
def ingest_status(request: Request):
    """Return status of connected agents and recent event counts."""
    verify_token(request)
    agents = processor.get_agent_status()
    events = processor.get_recent_events(limit=0)
    return {"agents": agents, "total_buffered": len(events)}


@router.get("/api/ingest/events")
def list_events(request: Request, limit: Optional[int] = Query(50, ge=1, le=500),
                source_type: Optional[str] = None):
    """Return recent ingested events."""
    verify_token(request)
    events = processor.get_recent_events(limit=limit, source_type=source_type)
    return {"events": events, "count": len(events)}
