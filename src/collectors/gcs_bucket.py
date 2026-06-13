# File: src/collectors/gcs_bucket.py
# Purpose: Monitor critical GCS buckets (object count, size, last modified)

import time
import logging
import threading

logger = logging.getLogger(__name__)

# Buckets to monitor: id -> bucket_name
MONITORED_BUCKETS = {
    "vault_data": "coldvault-vault-data",
}

_stats: dict = {}  # {bucket_id: {object_count, total_size_bytes, ...}}
_lock = threading.Lock()
_last_poll: float = 0

POLL_INTERVAL = 300  # 5 minutes


def _query_bucket(bucket_name: str) -> dict:
    """Query GCS bucket stats using storage API."""
    from google.cloud import storage
    client = storage.Client()
    bucket = client.bucket(bucket_name)

    if not bucket.exists():
        return {"status": "error", "error": "bucket_not_found"}

    # List objects and compute stats
    object_count = 0
    total_size = 0
    newest_ts = None

    for blob in client.list_blobs(bucket_name):
        object_count += 1
        total_size += blob.size or 0
        if blob.updated:
            if newest_ts is None or blob.updated > newest_ts:
                newest_ts = blob.updated

    # Bucket metadata
    bucket.reload()
    versioning = bucket.versioning_enabled
    location = bucket.location

    return {
        "status": "healthy",
        "object_count": object_count,
        "total_size_bytes": total_size,
        "total_size_mb": round(total_size / (1024 * 1024), 1),
        "last_modified": newest_ts.isoformat() if newest_ts else None,
        "versioning": versioning,
        "location": location,
        "bucket_name": bucket_name,
    }


def poll_once():
    """Poll all monitored buckets."""
    global _stats, _last_poll
    results = {}
    for bucket_id, bucket_name in MONITORED_BUCKETS.items():
        try:
            results[bucket_id] = _query_bucket(bucket_name)
            logger.info(f"GCS {bucket_name}: {results[bucket_id]['object_count']} objects, "
                        f"{results[bucket_id]['total_size_mb']} MB")
        except Exception as e:
            logger.warning(f"GCS bucket poll failed for {bucket_name}: {e}")
            results[bucket_id] = {"status": "error", "error": str(e),
                                  "bucket_name": bucket_name}
    with _lock:
        _stats = results
        _last_poll = time.time()


def poll_loop():
    """Background polling loop (runs in thread)."""
    stop = threading.Event()
    poll_once()
    while not stop.wait(POLL_INTERVAL):
        poll_once()


def get_stats() -> dict:
    """Return latest bucket stats."""
    with _lock:
        return dict(_stats)
