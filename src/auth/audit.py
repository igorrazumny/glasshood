# File: src/auth/audit.py
# Purpose: ALCOA+ audit trail for authentication and authorization events
#
# ALCOA+ compliance (Annex 11):
#   Attributable  — user + ip_address identify who
#   Legible       — human-readable action strings, no encoded data
#   Contemporaneous — timestamp recorded at event time (UTC ISO 8601)
#   Original      — event_id (UUID) marks first recording, entries immutable
#   Accurate      — structured fields, no free-text ambiguity
#   Complete      — customer_id, session_id, request context included
#   Consistent    — same schema for all entries
#   Enduring      — in-memory now, TODO: persist to BQ for long-term retention
#   Available     — queryable via /api/audit/auth with filters

import collections
import logging
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_auth_audit_log: collections.deque = collections.deque(maxlen=5000)


def log_auth_event(action: str, user: str = "", ip_address: str = "",
                   customer_id: str = "", session_id: str = "",
                   request_path: str = "", request_method: str = "",
                   details: dict = None):
    """Record an ALCOA+ compliant authentication/authorization event."""
    entry = {
        "event_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "user": user,
        "ip_address": ip_address,
        "customer_id": customer_id,
        "session_id": session_id,
        "request_path": request_path,
        "request_method": request_method,
    }
    if details:
        entry["details"] = details

    _auth_audit_log.append(entry)
    logger.info(f"Auth event: {action} user={user} customer={customer_id} ip={ip_address}")


def log_from_request(action: str, request, details: dict = None):
    """Log auth event with context extracted from a FastAPI Request object."""
    ctx = getattr(getattr(request, "state", None), "user_context", None) or {}
    ip = ""
    path = ""
    method = ""
    try:
        ip = request.client.host if request.client else ""
    except Exception:
        pass
    try:
        path = request.url.path
        method = request.method
    except Exception:
        pass

    log_auth_event(
        action=action,
        user=ctx.get("user", ""),
        ip_address=ip,
        customer_id=ctx.get("customer_id", ""),
        session_id=ctx.get("auth0_sub", ""),
        request_path=path,
        request_method=method,
        details=details,
    )


def get_auth_audit_log(customer_id: str = "", action: str = "",
                       limit: int = 200) -> list[dict]:
    """Return auth audit trail entries (most recent first), with optional filters."""
    entries = list(reversed(_auth_audit_log))
    if customer_id:
        entries = [e for e in entries if e.get("customer_id") == customer_id]
    if action:
        entries = [e for e in entries if e.get("action") == action]
    return entries[:limit]
