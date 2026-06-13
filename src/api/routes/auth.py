# File: src/api/routes/auth.py
# Purpose: Authentication — JWT sessions (Annex 11 §10.2), Auth0 SSO, API keys, RBAC

import hashlib
import logging
import secrets
import time
from datetime import datetime, timezone

import jwt as pyjwt

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.config.settings import (
    GLASSHOOD_PASSWORD, GLASSHOOD_LOGIN, GLASSHOOD_ADMIN_ROLE,
    AUTH0_DOMAIN, JWT_SECRET, JWT_ACCESS_TTL, JWT_REFRESH_TTL,
)
from src.auth.rbac import VALID_ROLES, require_role
from src.auth.audit import log_auth_event

logger = logging.getLogger(__name__)
router = APIRouter(tags=["auth"])

JWT_ALGORITHM = "HS256"

# Dev-mode fallback secret (lost on restart — set JWT_SECRET in production)
_DEV_SECRET = secrets.token_urlsafe(32)

# Refresh token store: jti -> {user, role, expiry}  (server-side for revocation)
_refresh_tokens: dict[str, dict] = {}

# API key store: key_hash -> {key_id, name, role, created_at, created_by}
_api_keys: dict[str, dict] = {}


class LoginRequest(BaseModel):
    login: str = ""
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class ApiKeyRequest(BaseModel):
    name: str
    role: str = "viewer"
    customer_id: str = ""


def _jwt_secret() -> str:
    if JWT_SECRET:
        return JWT_SECRET
    logger.warning("JWT_SECRET not set — using ephemeral dev secret")
    return _DEV_SECRET


def _make_access_token(user: str, role: str, customer_id: str = "") -> str:
    now = int(time.time())
    payload = {
        "sub": user, "role": role, "iat": now,
        "exp": now + JWT_ACCESS_TTL,
        "jti": secrets.token_hex(16), "type": "access",
    }
    if customer_id:
        payload["customer_id"] = customer_id
    return pyjwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGORITHM)


def _make_refresh_token(user: str, role: str, customer_id: str = "") -> str:
    now = int(time.time())
    jti = secrets.token_hex(16)
    payload = {
        "sub": user, "role": role, "iat": now,
        "exp": now + JWT_REFRESH_TTL,
        "jti": jti, "type": "refresh",
    }
    if customer_id:
        payload["customer_id"] = customer_id
    _refresh_tokens[jti] = {
        "user": user, "role": role, "expiry": now + JWT_REFRESH_TTL,
        "customer_id": customer_id,
    }
    return pyjwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGORITHM)


def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _determine_role(login: str) -> str:
    if GLASSHOOD_ADMIN_ROLE and login.lower() == GLASSHOOD_LOGIN.lower():
        return "admin"
    return "operator"


def _role_from_auth0(payload: dict) -> str:
    """Extract role from Auth0 token. Custom claim or default to admin for known users."""
    role = payload.get("https://glasshood.example.com/role")
    if role and role in VALID_ROLES:
        return role
    email = payload.get("email", payload.get("sub", ""))
    if email.lower() == GLASSHOOD_LOGIN.lower():
        return "admin"
    return "operator"


def verify_token(request: Request) -> dict:
    """Verify Bearer token (Auth0 JWT, local JWT, or API key).

    Auth order: Auth0 RS256 → local HS256 JWT → API key.
    Sets request.state.user_context. Returns {"user": str, "role": str}.
    """
    # Try Bearer token
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]

        # Try Auth0 JWT validation first (if Auth0 is configured)
        if AUTH0_DOMAIN:
            try:
                from src.auth.auth0_handler import get_auth0_handler
                payload = get_auth0_handler().validate_token(token)
                if payload:
                    email = payload.get("email", payload.get("sub", "unknown"))
                    role = _role_from_auth0(payload)
                    cid = payload.get("https://glasshood.example.com/customer_id", "")
                    ctx = {"user": email, "role": role, "customer_id": cid,
                           "auth0_sub": payload.get("sub")}
                    request.state.user_context = ctx
                    return ctx
            except Exception:
                pass  # Fall through to local JWT check

        # Try GCP Identity Token (service accounts — e.g., agent-neo)
        if token.count('.') == 2:
            try:
                import os
                import httpx as _httpx
                # Manually fetch JWKS and verify (avoids PyJWT vs python-jose conflicts)
                header = pyjwt.get_unverified_header(token)
                kid = header.get("kid")
                if kid and header.get("alg") == "RS256":
                    certs = _httpx.get("https://www.googleapis.com/oauth2/v1/certs", timeout=5).json()
                    pem_cert = certs.get(kid)
                    if pem_cert:
                        from cryptography.x509 import load_pem_x509_certificate
                        cert = load_pem_x509_certificate(pem_cert.encode())
                        public_key = cert.public_key()
                        cloud_run_url = os.getenv("GLASSHOOD_URL", "")
                        gcp_payload = pyjwt.decode(
                            token, public_key,
                            algorithms=["RS256"],
                            audience=cloud_run_url or None,
                            issuer="https://accounts.google.com",
                        )
                        sa_email = gcp_payload.get("email", "")
                        if sa_email.endswith(".iam.gserviceaccount.com"):
                            role = "viewer"  # Read-only RBAC
                            ctx = {"user": sa_email, "role": role, "customer_id": "",
                                   "auth_method": "gcp_identity"}
                            request.state.user_context = ctx
                            log_auth_event("gcp_identity_login", sa_email,
                                           details=f"GCP SA authenticated as {role}")
                            return ctx
            except Exception as gcp_err:
                logger.warning(f"GCP identity token check failed: {gcp_err}")

        # Local JWT (HS256 — issued by /api/auth/login)
        try:
            payload = pyjwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGORITHM])
        except pyjwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token expired")
        except pyjwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="Invalid token")
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Not an access token")
        ctx = {"user": payload["sub"], "role": payload["role"],
               "customer_id": payload.get("customer_id", "")}
        request.state.user_context = ctx
        return ctx

    # Try API key
    api_key = request.headers.get("X-API-Key", "")
    if api_key:
        key_hash = _hash_key(api_key)
        info = _api_keys.get(key_hash)
        if not info:
            raise HTTPException(status_code=401, detail="Invalid API key")
        ctx = {"user": f"apikey:{info['name']}", "role": info["role"],
               "customer_id": info.get("customer_id", "")}
        request.state.user_context = ctx
        return ctx

    raise HTTPException(status_code=401, detail="Missing authentication")


def _cleanup_refresh_tokens():
    now = time.time()
    expired = [jti for jti, info in _refresh_tokens.items() if info["expiry"] < now]
    for jti in expired:
        del _refresh_tokens[jti]


@router.post("/api/auth/login")
def login(body: LoginRequest):
    """Authenticate with password, return JWT access + refresh tokens."""
    if not GLASSHOOD_PASSWORD:
        raise HTTPException(status_code=500, detail="Auth not configured")
    # Demo user: read-only viewer access with masking
    is_demo = body.login.lower() == 'demo@glasshood.example.com' and body.password == 'demo'
    if not is_demo:
        if GLASSHOOD_LOGIN and body.login.lower() != GLASSHOOD_LOGIN.lower():
            log_auth_event("login_failed", user=body.login, details={"reason": "invalid_login"})
            raise HTTPException(status_code=401, detail="Invalid credentials")
        if body.password != GLASSHOOD_PASSWORD:
            log_auth_event("login_failed", user=body.login, details={"reason": "invalid_password"})
            raise HTTPException(status_code=401, detail="Invalid credentials")

    role = "viewer" if is_demo else _determine_role(body.login)
    access_token = _make_access_token(body.login, role)
    refresh_token = _make_refresh_token(body.login, role)
    _cleanup_refresh_tokens()
    log_auth_event("login", user=body.login, details={"role": role})
    return {
        "token": access_token,
        "refresh_token": refresh_token,
        "expires_in": JWT_ACCESS_TTL,
        "role": role,
    }


@router.post("/api/auth/refresh")
def refresh(body: RefreshRequest):
    """Exchange a valid refresh token for a new access token (Annex 11 idle timeout)."""
    try:
        payload = pyjwt.decode(body.refresh_token, _jwt_secret(), algorithms=[JWT_ALGORITHM])
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Refresh token expired — re-login required")
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Not a refresh token")

    jti = payload.get("jti", "")
    if jti not in _refresh_tokens:
        raise HTTPException(status_code=401, detail="Refresh token revoked")

    user = payload["sub"]
    role = payload["role"]
    cid = payload.get("customer_id", "")
    access_token = _make_access_token(user, role, customer_id=cid)
    log_auth_event("token_refreshed", user=user)
    return {"token": access_token, "expires_in": JWT_ACCESS_TTL, "role": role}


@router.get("/api/auth/me")
def get_me(request: Request):
    """Return current user's auth context (user, role, customer_id)."""
    ctx = verify_token(request)
    return {
        "user": ctx["user"],
        "role": ctx["role"],
        "customer_id": ctx.get("customer_id", ""),
    }


@router.post("/api/auth/logout")
def logout(request: Request, body: RefreshRequest):
    """Revoke a refresh token (logout). Returns success even if already revoked."""
    verify_token(request)
    try:
        payload = pyjwt.decode(body.refresh_token, _jwt_secret(), algorithms=[JWT_ALGORITHM])
        jti = payload.get("jti", "")
        if jti in _refresh_tokens:
            user = _refresh_tokens[jti].get("user", "")
            del _refresh_tokens[jti]
            log_auth_event("logout", user=user)
    except pyjwt.InvalidTokenError:
        pass  # Already invalid — treat as success
    return {"status": "logged_out"}


@router.get("/api/auth/sessions")
def list_sessions(request: Request):
    """List active refresh tokens (admin only). Shows user, role, expiry."""
    verify_token(request)
    require_role(request, "admin")

    ctx = request.state.user_context
    user_cid = ctx.get("customer_id", "")
    now = time.time()
    sessions = []
    for jti, info in _refresh_tokens.items():
        if info["expiry"] < now:
            continue
        # Customer-scoped admins only see their own customer's sessions
        if user_cid and info.get("customer_id", "") != user_cid:
            continue
        sessions.append({
            "user": info["user"],
            "role": info["role"],
            "customer_id": info.get("customer_id", ""),
            "expires_at": datetime.fromtimestamp(info["expiry"], tz=timezone.utc).isoformat(),
        })
    return {"sessions": sessions, "count": len(sessions)}


@router.post("/api/auth/api-keys")
def create_api_key(request: Request, body: ApiKeyRequest):
    """Create a new API key (admin only). Returns the key once — store it."""
    verify_token(request)
    require_role(request, "admin")

    if body.role not in VALID_ROLES:
        raise HTTPException(status_code=400,
                            detail=f"Invalid role. Valid: {sorted(VALID_ROLES)}")

    key = secrets.token_urlsafe(32)
    key_id = secrets.token_hex(8)
    key_hash = _hash_key(key)
    now_iso = datetime.now(timezone.utc).isoformat()

    ctx = request.state.user_context
    _api_keys[key_hash] = {
        "key_id": key_id,
        "name": body.name,
        "role": body.role,
        "customer_id": body.customer_id,
        "created_at": now_iso,
        "created_by": ctx["user"],
    }

    log_auth_event("api_key_created", user=ctx["user"],
                   details={"key_id": key_id, "name": body.name,
                            "role": body.role, "customer_id": body.customer_id})
    return {
        "key_id": key_id,
        "api_key": key,
        "name": body.name,
        "role": body.role,
        "created_at": now_iso,
    }


@router.get("/api/auth/api-keys")
def list_api_keys(request: Request):
    """List all API keys (admin only). Keys are not returned — only metadata."""
    verify_token(request)
    require_role(request, "admin")

    keys = [
        {
            "key_id": info["key_id"],
            "name": info["name"],
            "role": info["role"],
            "created_at": info["created_at"],
            "created_by": info["created_by"],
        }
        for info in _api_keys.values()
    ]
    return {"api_keys": keys, "count": len(keys)}


@router.delete("/api/auth/api-keys/{key_id}")
def revoke_api_key(request: Request, key_id: str):
    """Revoke an API key by key_id (admin only)."""
    verify_token(request)
    require_role(request, "admin")

    for key_hash, info in list(_api_keys.items()):
        if info["key_id"] == key_id:
            del _api_keys[key_hash]
            ctx = request.state.user_context
            log_auth_event("api_key_revoked", user=ctx["user"],
                           details={"key_id": key_id, "name": info["name"]})
            return {"status": "revoked", "key_id": key_id}

    raise HTTPException(status_code=404, detail="API key not found")
