# File: src/api/routes/alerts.py
# Purpose: GET /api/alerts, POST /api/alerts/ack — Layer 1 rule engine alerts

from fastapi import APIRouter, Request, Query, HTTPException
from pydantic import BaseModel
from typing import Optional

from src.api.routes.auth import verify_token
from src.auth.rbac import require_role
from src.rules.engine import get_alerts, acknowledge_alert

router = APIRouter(tags=["alerts"])


@router.get("/api/alerts")
def list_alerts(request: Request, severity: Optional[str] = Query(None)):
    """Return active alerts. Optional ?severity=critical|warning|info filter."""
    verify_token(request)
    alerts = get_alerts()
    if severity:
        alerts = [a for a in alerts if a.get("severity") == severity]
    return {"alerts": alerts, "count": len(alerts)}


class AckRequest(BaseModel):
    rule_id: str
    node_id: Optional[str] = None
    user: str


@router.post("/api/alerts/ack")
def ack_alert(request: Request, body: AckRequest):
    """Acknowledge an active alert. ALCOA+ audit-trailed. Requires operator role."""
    verify_token(request)
    require_role(request, "operator")
    found = acknowledge_alert(body.rule_id, body.node_id, body.user)
    if not found:
        raise HTTPException(status_code=404, detail="Alert not found or already acknowledged")
    return {"status": "acknowledged", "rule_id": body.rule_id, "node_id": body.node_id}
