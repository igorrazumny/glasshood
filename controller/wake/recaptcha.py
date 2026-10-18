# File: controller/wake/recaptcha.py
# Purpose: REQ-GHA-018 clause 5 — only a browser that ran the page can wake the app.
# A wake carries a reCAPTCHA v3 token; Google confirms it, and the hostname, action
# and score must match. A raw request has no valid token and changes nothing.

from __future__ import annotations

import httpx

VERIFY_URL = "https://www.google.com/recaptcha/api/siteverify"
MIN_SCORE = 0.3
ACTION = "wake"


def check(result: dict, allowed_hosts: set[str]) -> bool:
    """Judge Google's siteverify answer."""
    return (
        result.get("success") is True
        and result.get("action") == ACTION
        and result.get("hostname") in allowed_hosts
        and float(result.get("score", 0)) >= MIN_SCORE
    )


def verify(secret: str, token: str, allowed_hosts: set[str], timeout: float = 5.0) -> bool:
    if not token or not secret:
        return False
    try:
        r = httpx.post(VERIFY_URL, data={"secret": secret, "response": token}, timeout=timeout)
        r.raise_for_status()
        return check(r.json(), allowed_hosts)
    except (httpx.HTTPError, ValueError):
        return False
