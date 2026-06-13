# File: src/collectors/gcp_logging.py
# Purpose: Poll GCP Cloud Logging for error counts and recent events

import asyncio
import time
import logging
from datetime import datetime, timezone, timedelta

from src.config.settings import GCP_PROJECT_ID, GCP_POLL_INTERVAL

logger = logging.getLogger(__name__)

_stats: dict = {"error_count_15m": 0, "recent_errors": [], "last_poll": 0}


async def poll_once():
    """Query Cloud Logging for recent errors."""
    global _stats
    try:
        from google.cloud.logging_v2 import Client

        # Run blocking client call in executor
        loop = asyncio.get_running_loop()

        def _query():
            client = Client(project=GCP_PROJECT_ID)
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
            filter_str = (
                f'resource.type="gce_instance" '
                f'severity>=ERROR '
                f'timestamp>="{cutoff.isoformat()}"'
            )
            entries = list(client.list_entries(
                filter_=filter_str,
                order_by="timestamp desc",
                max_results=50,
            ))
            errors = []
            for entry in entries[:10]:  # Last 10 for display
                errors.append({
                    "timestamp": str(entry.timestamp),
                    "severity": entry.severity,
                    "message": str(entry.payload)[:200] if entry.payload else "",
                })
            return len(entries), errors

        count, errors = await loop.run_in_executor(None, _query)
        _stats = {
            "error_count_15m": count,
            "recent_errors": errors,
            "last_poll": time.time(),
        }
    except Exception as e:
        logger.warning(f"GCP Logging poll failed: {e}")
        _stats["last_poll"] = time.time()


async def poll_loop():
    """Background polling loop."""
    while True:
        try:
            await poll_once()
        except Exception as e:
            logger.error(f"GCP Logging poll loop error: {e}")
        await asyncio.sleep(GCP_POLL_INTERVAL)


def get_stats() -> dict:
    return _stats
