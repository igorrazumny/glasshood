# File: src/collectors/gcp_logging.py
# Purpose: Poll GCP Cloud Logging for error counts and recent events

import asyncio
import time
import logging
from datetime import datetime, timezone, timedelta

from src.collectors import alarm_sources
from src.config.settings import GCP_POLL_INTERVAL

logger = logging.getLogger(__name__)

# Counts only the errors the manifest's alarm_sources.errors filter selects, i.e. the
# monitored system's own failures, and names the part they belong to (REQ-GHA-027).
# read_at: time of the last successful reading (failed polls leave it unchanged).
# error_count_15m is None while nothing was read: an alarm on it is "not checked".
_stats: dict = {"error_count_15m": None, "recent_errors": [], "last_poll": 0,
                "read_at": None, "part": None}

_MAX_COUNTED = 1000


async def poll_once():
    """Query Cloud Logging for the monitored system's recent errors."""
    global _stats
    source = alarm_sources.load().get("errors")
    if not source:
        _stats = {"error_count_15m": None, "recent_errors": [], "last_poll": time.time(),
                  "read_at": None, "part": None}
        return
    try:
        from google.cloud.logging_v2 import Client

        # Run blocking client call in executor
        loop = asyncio.get_running_loop()

        def _query():
            client = Client(project=source["project"])
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
            filter_str = f'({source["filter"]}) AND timestamp>="{cutoff.isoformat()}"'
            entries = list(client.list_entries(
                filter_=filter_str,
                order_by="timestamp desc",
                max_results=_MAX_COUNTED,
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
        now = time.time()
        _stats = {
            "error_count_15m": count,
            "recent_errors": errors,
            "last_poll": now,
            "read_at": now,
            "part": source["part"],
        }
        # Judge this reading now, not when someone opens the page (REQ-GHA-026)
        from src.security.anomaly_detector import judge_fresh_readings
        judge_fresh_readings()
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
