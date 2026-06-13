# File: src/collectors/coldvault.py
# Purpose: Poll ColdVault /api/health and /api/metrics endpoints

import asyncio
import time
import logging

import httpx

from src.config.settings import COLDVAULT_URL, COLDVAULT_ADMIN_KEY, COLDVAULT_POLL_INTERVAL

logger = logging.getLogger(__name__)

# Cached state
_health: dict = {}
_metrics: dict = {}
_last_poll: float = 0
_last_error: str = ""


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

        # Metrics (admin key required)
        if COLDVAULT_ADMIN_KEY:
            try:
                resp = await client.get(
                    f"{COLDVAULT_URL}/api/metrics",
                    headers={"X-Admin-Key": COLDVAULT_ADMIN_KEY},
                )
                resp.raise_for_status()
                _metrics = resp.json()
            except Exception as e:
                logger.warning(f"ColdVault metrics poll failed: {e}")
                _metrics = {"error": str(e)}
        else:
            _metrics = {"error": "No admin key configured"}

    _last_poll = time.time()
    _last_error = ""


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


def get_last_poll() -> float:
    return _last_poll


def is_stale() -> bool:
    """Data is stale if last poll was > 2x interval ago."""
    if _last_poll == 0:
        return True
    return (time.time() - _last_poll) > (COLDVAULT_POLL_INTERVAL * 2)
