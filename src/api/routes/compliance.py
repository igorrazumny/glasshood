# File: src/api/routes/compliance.py
# Purpose: Compliance report generation API — Annex 11, ALCOA+, 21 CFR Part 11

from fastapi import APIRouter, Request, Query, HTTPException
from typing import Optional

from src.api.routes.auth import verify_token
from src.compliance.report_engine import (
    generate_report, get_available_report_types, get_report_audit_log,
    VALID_REPORT_TYPES,
)

router = APIRouter(tags=["compliance"])


@router.get("/api/compliance/report-types")
def list_report_types(request: Request):
    """Return available compliance report types."""
    verify_token(request)
    return {"report_types": get_available_report_types()}


@router.get("/api/compliance/report")
def create_report(
    request: Request,
    report_type: str = Query("full"),
    period_start: Optional[str] = Query(None),
    period_end: Optional[str] = Query(None),
):
    """Generate a compliance evidence report on demand.

    Returns structured JSON mapped to regulatory requirements.
    """
    verify_token(request)
    if report_type not in VALID_REPORT_TYPES:
        raise HTTPException(status_code=400,
                            detail=f"Invalid report_type. Valid: {sorted(VALID_REPORT_TYPES)}")
    return generate_report(report_type, period_start, period_end)


@router.get("/api/compliance/audit")
def compliance_audit_log(request: Request,
                         limit: Optional[int] = Query(50, ge=1, le=100)):
    """Return ALCOA+ audit trail of compliance report generation events."""
    verify_token(request)
    entries = get_report_audit_log()
    if limit:
        entries = entries[:limit]
    return {"entries": entries, "count": len(entries)}
