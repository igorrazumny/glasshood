# File: controller/wake/tokens.py
# Purpose: REQ-GHA-018 use tokens. A successful wake hands the page a signed token
# bound to the current wake (wake_id) and valid 3 hours. /use requires one. It is a
# bearer token: a copy can be replayed until it expires, and it is renewed only
# through a fresh reCAPTCHA, never by itself.

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone

USE_TOKEN_SECONDS = 3 * 3600


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def issue(secret: bytes, wake_id: str, now: float) -> dict:
    exp = int(now) + USE_TOKEN_SECONDS
    body = _b64(json.dumps({"w": wake_id, "exp": exp}, separators=(",", ":")).encode())
    sig = _b64(hmac.new(secret, body.encode(), hashlib.sha256).digest())
    return {
        "use_token": f"{body}.{sig}",
        "use_token_expires": datetime.fromtimestamp(exp, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def valid(secret: bytes, token: str, wake_id: str, now: float) -> bool:
    """True only for an unexpired token, correctly signed, for the current wake."""
    try:
        body, sig = token.split(".")
        expected = _b64(hmac.new(secret, body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return False
        claims = json.loads(_unb64(body))
    except (ValueError, TypeError):
        return False
    return bool(wake_id) and claims.get("w") == wake_id and now < claims.get("exp", 0)
