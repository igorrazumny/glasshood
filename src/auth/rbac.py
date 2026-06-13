# File: src/auth/rbac.py
# Purpose: Role-based access control — role hierarchy and enforcement

from fastapi import HTTPException, Request

ROLE_HIERARCHY = {"admin": 3, "operator": 2, "viewer": 1}
VALID_ROLES = set(ROLE_HIERARCHY.keys())


def get_role_level(role: str) -> int:
    """Return numeric level for a role. Unknown roles get 0."""
    return ROLE_HIERARCHY.get(role, 0)


def require_role(request: Request, min_role: str):
    """Check that the authenticated user has at least min_role.

    Must be called AFTER verify_token(). Uses request.state.user_context
    set by verify_token.

    Raises HTTPException(403) if insufficient role.
    """
    ctx = getattr(request.state, "user_context", None)
    if not ctx:
        raise HTTPException(status_code=401, detail="Not authenticated")

    user_level = get_role_level(ctx.get("role", ""))
    required_level = get_role_level(min_role)

    if user_level < required_level:
        from src.auth.audit import log_auth_event
        log_auth_event("role_check_failed", user=ctx.get("user", ""),
                       details={"required": min_role, "actual": ctx.get("role")})
        raise HTTPException(
            status_code=403,
            detail=f"Insufficient role: requires {min_role}, have {ctx.get('role')}",
        )
    return ctx


def require_customer(request: Request, customer_id: str):
    """Check that authenticated user has access to customer_id.

    Admins without a customer_id scope (super-admin) can access all customers.
    Users scoped to a customer_id can only access their own.
    Must be called AFTER verify_token().
    """
    ctx = getattr(request.state, "user_context", None)
    if not ctx:
        raise HTTPException(status_code=401, detail="Not authenticated")

    user_cid = ctx.get("customer_id", "")
    # Super-admin (no customer_id scope) can access any customer
    if not user_cid:
        return ctx
    # Scoped user must match
    if user_cid != customer_id:
        from src.auth.audit import log_auth_event
        log_auth_event("customer_access_denied", user=ctx.get("user", ""),
                       details={"requested": customer_id, "scoped_to": user_cid})
        raise HTTPException(
            status_code=403,
            detail=f"Access denied: scoped to customer {user_cid}",
        )
    return ctx
