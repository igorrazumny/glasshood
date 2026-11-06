# File: src/api/routes/alerts.py
# Purpose: GET /api/alerts, POST /api/alerts/ack — Layer 1 rule engine alerts;
# REQ-GHA-029: one alarm with its report, "Investigate deeper" and its follow-up

from fastapi import APIRouter, Request, Query, HTTPException
from pydantic import BaseModel
from typing import Optional

from src.api.routes.auth import verify_token
from src.auth.rbac import get_role_level, require_role
from src.rules.engine import get_alerts, acknowledge_alert, find_alarm

router = APIRouter(tags=["alerts"])


def _signed_in_user(request: Request) -> str:
    ctx = getattr(request.state, "user_context", None) or {}
    return ctx.get("user") or "unknown"


@router.get("/api/alerts")
def list_alerts(request: Request, severity: Optional[str] = Query(None)):
    """Return active alerts. Optional ?severity=critical|warning|info filter."""
    verify_token(request)
    alerts = get_alerts()
    if severity:
        alerts = [a for a in alerts if a.get("severity") == severity]
    return {"alerts": alerts, "count": len(alerts)}


@router.get("/api/alerts/one")
def one_alert(request: Request, group: str, node_id: Optional[str] = None):
    """One alarm (open, or ended within the day) with its report, if any."""
    verify_token(request)
    alarm = find_alarm(group, node_id)
    if alarm is None:
        raise HTTPException(status_code=404, detail="Alarm not found")
    # Whether this user may acknowledge, investigate and follow up (operators and above)
    ctx = getattr(request.state, "user_context", None) or {}
    alarm["can_act"] = get_role_level(ctx.get("role", "")) >= get_role_level("operator")
    return alarm


@router.get("/api/alerts/ai-review")
def ai_review_status(request: Request):
    """When the AI log review last ran, and what it found."""
    verify_token(request)
    from src.analysis import ai_review
    return ai_review.status()


class AckRequest(BaseModel):
    rule_id: str  # the alarm's group (its rule id for older clients)
    node_id: Optional[str] = None
    user: Optional[str] = None  # ignored: the signed-in user is recorded (REQ-GHA-029 clause 2)


@router.post("/api/alerts/ack")
def ack_alert(request: Request, body: AckRequest):
    """Acknowledge an active alert. ALCOA+ audit-trailed. Requires operator role."""
    verify_token(request)
    require_role(request, "operator")
    found = acknowledge_alert(body.rule_id, body.node_id, _signed_in_user(request))
    if not found:
        raise HTTPException(status_code=404, detail="Alert not found or already acknowledged")
    from src.analysis import ai_review
    ai_review.save()
    return {"status": "acknowledged", "rule_id": body.rule_id, "node_id": body.node_id}


class AlarmRef(BaseModel):
    group: str
    node_id: Optional[str] = None


@router.post("/api/alerts/investigate", status_code=202)
def investigate(request: Request, body: AlarmRef):
    """Start one investigation of one alarm; the report is saved with the alarm."""
    verify_token(request)
    require_role(request, "operator")
    from src.analysis import ai_investigate
    from src.api.routes.topology import get_topology_data
    why = ai_investigate.start(body.group, body.node_id, _signed_in_user(request), get_topology_data())
    if why:
        raise HTTPException(status_code=404 if why == "alarm not found" else 409, detail=why)
    return {"status": "running"}


@router.post("/api/alerts/followup")
def followup(request: Request, body: AlarmRef):
    """Add what happened since the report (or the last follow-up)."""
    verify_token(request)
    require_role(request, "operator")
    from src.analysis import ai_investigate
    from src.api.routes.topology import get_topology_data
    entry, why = ai_investigate.followup(body.group, body.node_id, _signed_in_user(request),
                                         get_topology_data())
    if why:
        raise HTTPException(status_code=409, detail=why)
    return entry
