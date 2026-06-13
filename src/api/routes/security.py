# File: src/api/routes/security.py
# Purpose: CVE scanner findings API — list, filter, update remediation status

from fastapi import APIRouter, Request, Query, HTTPException
from pydantic import BaseModel
from typing import Optional

from src.api.routes.auth import verify_token
from src.security.cve_scanner import get_findings, get_stats, update_finding_status

router = APIRouter(tags=["security"])


@router.get("/api/security/findings")
def list_findings(request: Request, severity: Optional[str] = Query(None)):
    """Return CVE findings. Optional ?severity=critical|high|medium|low filter."""
    verify_token(request)
    findings = get_findings()
    if severity:
        findings = [f for f in findings if f.get("severity") == severity]
    return {"findings": findings, "count": len(findings)}


@router.get("/api/security/summary")
def findings_summary(request: Request):
    """Return CVE findings summary — counts by severity and GxP impact."""
    verify_token(request)
    stats = get_stats()
    return {"security": stats}


class FindingStatusRequest(BaseModel):
    status: str  # acknowledged, mitigated, accepted
    user: str


@router.post("/api/security/findings/{cve_id}/status")
def update_status(request: Request, cve_id: str, body: FindingStatusRequest):
    """Update remediation status of a CVE finding. ALCOA+ audit-trailed."""
    verify_token(request)
    found = update_finding_status(cve_id, body.status, body.user)
    if not found:
        raise HTTPException(status_code=404, detail="CVE finding not found or invalid status")
    return {"status": "updated", "cve_id": cve_id, "new_status": body.status}
