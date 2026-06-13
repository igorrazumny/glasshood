# File: src/analysis/black_box.py
# Purpose: Local-first telemetry spool — writes to disk, flushes to GCS

import json
import logging
import os
import time
from pathlib import Path

from src.config.settings import (
    BLACKBOX_ENABLED, BLACKBOX_LOCAL_DIR, BLACKBOX_BUCKET,
    ANALYSIS_INTERVAL,
)

logger = logging.getLogger(__name__)

_last_buffer_time: float = 0


def _ensure_dir(path: str) -> Path:
    """Create spool directory if needed."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def buffer_telemetry(topology: dict, analysis: dict, event: str = "analysis") -> bool:
    """Write telemetry to local spool. Rate-limited to 1/ANALYSIS_INTERVAL."""
    global _last_buffer_time

    if not BLACKBOX_ENABLED:
        return False

    now = time.time()
    if (now - _last_buffer_time) < ANALYSIS_INTERVAL:
        return False

    try:
        spool = _ensure_dir(BLACKBOX_LOCAL_DIR)
        filename = f"{event}-{int(now)}.json"
        record = {
            "timestamp": now,
            "event": event,
            "topology_summary": {
                "node_count": len(topology.get("nodes", [])),
                "overall_status": topology.get("overall_status", "unknown"),
            },
            "analysis": {
                "score": analysis.get("score"),
                "summary": analysis.get("summary", ""),
                "stale": analysis.get("stale", True),
            },
        }
        filepath = spool / filename
        filepath.write_text(json.dumps(record, indent=2))
        _last_buffer_time = now
        logger.debug(f"Buffered telemetry: {filename}")
        return True
    except Exception as e:
        logger.warning(f"Failed to buffer telemetry: {e}")
        return False


def flush_to_gcs() -> int:
    """Upload buffered files to Cloud Storage, delete local copies. Returns count."""
    if not BLACKBOX_ENABLED or not BLACKBOX_BUCKET:
        return 0

    spool = Path(BLACKBOX_LOCAL_DIR)
    if not spool.exists():
        return 0

    files = sorted(spool.glob("*.json"))
    if not files:
        return 0

    try:
        from google.cloud import storage
        client = storage.Client()
        bucket = client.bucket(BLACKBOX_BUCKET)
    except Exception as e:
        logger.warning(f"GCS unavailable, keeping local spool: {e}")
        return 0

    flushed = 0
    for f in files:
        try:
            blob = bucket.blob(f"glasshood-blackbox/{f.name}")
            blob.upload_from_filename(str(f))
            f.unlink()
            flushed += 1
        except Exception as e:
            logger.warning(f"Failed to upload {f.name}: {e}")
            break

    if flushed:
        logger.info(f"Flushed {flushed} telemetry records to GCS")
    return flushed


def pending_count() -> int:
    """Return number of pending local spool files."""
    spool = Path(BLACKBOX_LOCAL_DIR)
    if not spool.exists():
        return 0
    return len(list(spool.glob("*.json")))
