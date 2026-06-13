# File: src/api/routes/audit.py
# Purpose: ALCOA+ audit trail endpoints for all monitoring modules

from fastapi import APIRouter, Request, Query
from typing import Optional

from src.api.routes.auth import verify_token
from src.rules.engine import get_audit_log
from src.security.cve_scanner import get_audit_log as get_cve_audit_log
from src.security.anomaly_detector import get_audit_log as get_anomaly_audit_log
from src.security.correlator import get_audit_log as get_correlator_audit_log
from src.integrations.sync import get_audit_log as get_snow_audit_log
from src.auth.audit import get_auth_audit_log
from src.storage.pipeline import get_audit_log as get_storage_audit_log

router = APIRouter(tags=["audit"])


@router.get("/api/audit/rules")
def rules_audit_log(request: Request, limit: Optional[int] = Query(50, ge=1, le=500)):
    """Return ALCOA+ audit trail of rule evaluation cycles (most recent first)."""
    verify_token(request)
    entries = get_audit_log()
    if limit:
        entries = entries[:limit]
    return {"entries": entries, "count": len(entries)}


@router.get("/api/audit/security")
def security_audit_log(request: Request, limit: Optional[int] = Query(50, ge=1, le=200)):
    """Return ALCOA+ audit trail for CVE security scans."""
    verify_token(request)
    entries = get_cve_audit_log()
    if limit:
        entries = entries[:limit]
    return {"entries": entries, "count": len(entries)}


@router.get("/api/audit/anomalies")
def anomaly_audit_log(request: Request, limit: Optional[int] = Query(50, ge=1, le=200)):
    """Return ALCOA+ audit trail for anomaly detection cycles."""
    verify_token(request)
    entries = get_anomaly_audit_log()
    if limit:
        entries = entries[:limit]
    return {"entries": entries, "count": len(entries)}


@router.get("/api/audit/correlations")
def correlation_audit_log(request: Request, limit: Optional[int] = Query(50, ge=1, le=200)):
    """Return ALCOA+ audit trail for operational-anomaly correlations."""
    verify_token(request)
    entries = get_correlator_audit_log()
    if limit:
        entries = entries[:limit]
    return {"entries": entries, "count": len(entries)}


@router.get("/api/audit/snow")
def snow_audit_log(request: Request, limit: Optional[int] = Query(50, ge=1, le=500)):
    """Return ALCOA+ audit trail for ServiceNow sync and correlation operations."""
    verify_token(request)
    entries = get_snow_audit_log()
    if limit:
        entries = entries[:limit]
    return {"entries": entries, "count": len(entries)}


@router.get("/api/audit/auth")
def auth_audit_log(request: Request, limit: Optional[int] = Query(50, ge=1, le=500)):
    """Return ALCOA+ audit trail for authentication and authorization events."""
    verify_token(request)
    entries = get_auth_audit_log()
    if limit:
        entries = entries[:limit]
    return {"entries": entries, "count": len(entries)}


@router.get("/api/audit/storage")
def storage_audit_log(request: Request, limit: Optional[int] = Query(50, ge=1, le=500)):
    """Return ALCOA+ audit trail for storage pipeline operations."""
    verify_token(request)
    entries = get_storage_audit_log()
    if limit:
        entries = entries[:limit]
    return {"entries": entries, "count": len(entries)}
