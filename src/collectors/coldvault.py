# File: src/collectors/coldvault.py
# Purpose: Poll ColdVault /api/health and /api/metrics endpoints

import asyncio
import time
import logging

import httpx

from src.collectors import coldvault_identity
from src.config.settings import COLDVAULT_URL, COLDVAULT_POLL_INTERVAL

logger = logging.getLogger(__name__)

# Cached state
_health: dict = {}
_metrics: dict = {}
_last_poll: float = 0
_last_error: str = ""
# REQ-GHA-025: whether the last metrics read worked, why not, and when it was tried
_metrics_status: dict = {"read": False, "reason": "not read yet", "checked_at": None}


async def poll_once():
    """Poll ColdVault health and metrics once."""
    global _health, _metrics, _last_poll, _last_error

    async with httpx.AsyncClient(timeout=10.0, verify=True) as client:
        # Health (unauthenticated)
        try:
            resp = await client.get(f"{COLDVAULT_URL}/api/health")
            resp.raise_for_status()
            _health = resp.json()
        except Exception as e:
            logger.warning(f"ColdVault health poll failed: {e}")
            _last_error = str(e)
            _health = {"status": "unreachable", "error": str(e)}

    # Metrics: GlassHood's own short-lived identity token, no key (REQ-GHA-025)
    await _poll_metrics()

    _last_poll = time.time()
    _last_error = ""


def _not_read(reason: str, checked_at: float) -> None:
    """Drop the old numbers and say why they are missing (REQ-GHA-025 clause 5)."""
    global _metrics, _metrics_status
    _metrics = {"error": reason}
    _metrics_status = {"read": False, "reason": reason, "checked_at": checked_at}
    logger.warning(f"ColdVault metrics not read: {reason}")


async def _poll_metrics():
    global _metrics, _metrics_status
    checked_at = time.time()
    loop = asyncio.get_running_loop()
    try:
        token = await loop.run_in_executor(None, coldvault_identity.id_token)
    except coldvault_identity.IdentityNotConfigured as e:
        return _not_read(str(e), checked_at)
    except Exception as e:
        # The type only: an auth library error can echo response bodies
        return _not_read(f"identity token not obtained ({type(e).__name__})", checked_at)
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=True) as client:
            resp = await client.get(f"{COLDVAULT_URL}/api/metrics",
                                    headers={"Authorization": f"Bearer {token}"})
    except Exception as e:
        return _not_read(f"ColdVault not reachable ({type(e).__name__})", checked_at)
    if resp.status_code != 200:
        return _not_read(f"ColdVault refused the request (HTTP {resp.status_code})", checked_at)
    try:
        data = resp.json()
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return _not_read("ColdVault answered with no readable metrics", checked_at)
    _metrics = data
    _metrics_status = {"read": True, "reason": "", "checked_at": checked_at}


async def poll_loop():
    """Background polling loop."""
    while True:
        try:
            await poll_once()
        except Exception as e:
            logger.error(f"ColdVault poll loop error: {e}")
        await asyncio.sleep(COLDVAULT_POLL_INTERVAL)


def get_health() -> dict:
    return _health


def get_metrics() -> dict:
    return _metrics


def get_metrics_status() -> dict:
    """Whether ColdVault's metrics were read, and if not why, with the time tried."""
    return dict(_metrics_status)


def get_last_poll() -> float:
    return _last_poll


def is_stale() -> bool:
    """Data is stale if last poll was > 2x interval ago."""
    if _last_poll == 0:
        return True
    return (time.time() - _last_poll) > (COLDVAULT_POLL_INTERVAL * 2)
