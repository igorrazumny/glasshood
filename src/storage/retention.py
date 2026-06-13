# File: src/storage/retention.py
# Purpose: Cold tier archival — export aged BigQuery rows to GCS as NDJSON

import collections
import json
import logging
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

from src.config.settings import (
    STORAGE_ENABLED, STORAGE_BQ_PROJECT, STORAGE_BQ_DATASET,
    STORAGE_BQ_TABLE, RETENTION_ENABLED, RETENTION_CONFIG_PATH,
    RETENTION_ARCHIVE_BUCKET,
)
from src.storage.customer_routing import (
    get_table_ref_for_customer, get_bucket_for_customer,
)

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_audit_log: collections.deque = collections.deque(maxlen=500)
_stats = {"archived": 0, "archive_runs": 0}
_stop = threading.Event()

_DEFAULT_CONFIG = {
    "hot_days": 7,
    "archive_after_days": 7,
    "archive_prefix": "glasshood-archive",
    # No partition_expiration_days — GxP: never auto-delete production data
}


def load_retention_config() -> dict:
    """Load retention config from YAML. Falls back to defaults."""
    try:
        path = Path(RETENTION_CONFIG_PATH)
        if path.exists():
            with open(path) as f:
                data = yaml.safe_load(f) or {}
            config = dict(_DEFAULT_CONFIG)
            config.update({k: v for k, v in data.items() if v is not None})
            return config
    except Exception as e:
        logger.warning(f"Failed to load retention config: {e}")
    return dict(_DEFAULT_CONFIG)


def archive_to_cold(customer_id: str = "") -> int:
    """Query BigQuery for events older than archive_after_days, export to GCS.
    Routes to per-customer dataset and bucket when customer_id is provided.
    """
    if not RETENTION_ENABLED or not STORAGE_ENABLED:
        return 0
    bucket_name = get_bucket_for_customer(customer_id)
    if not bucket_name:
        return 0

    config = load_retention_config()
    archive_after = config.get("archive_after_days", 7)
    prefix = config.get("archive_prefix", "glasshood-archive")
    cutoff = datetime.now(timezone.utc) - timedelta(days=archive_after)

    try:
        from google.cloud import bigquery
        client = bigquery.Client(project=STORAGE_BQ_PROJECT)
        table_ref = get_table_ref_for_customer(customer_id)
        # F-004: Use explicit timestamp bounds for partition filter compliance
        archive_floor = datetime.now(timezone.utc) - timedelta(days=archive_after + 365)
        query = f"""
            SELECT * FROM `{table_ref}`
            WHERE timestamp < @cutoff
            AND timestamp >= @archive_floor
            ORDER BY timestamp
            LIMIT 10000
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("cutoff", "TIMESTAMP", cutoff.isoformat()),
                bigquery.ScalarQueryParameter("archive_floor", "TIMESTAMP", archive_floor.isoformat()),
            ]
        )
        result = client.query(query, job_config=job_config)
        rows = [dict(row) for row in result]
    except Exception as e:
        logger.warning(f"BigQuery archive query failed: {e}")
        _log_action("archive_query", "failure", 0)
        return 0

    if not rows:
        _stats["archive_runs"] += 1
        _log_action("archive_to_cold", "noop", 0)
        return 0

    # Write NDJSON to GCS
    now = datetime.now(timezone.utc)
    blob_path = f"{prefix}/{now.strftime('%Y/%m/%d')}/batch-{int(now.timestamp())}.ndjson"
    ndjson = "\n".join(_serialize_row(r) for r in rows)

    try:
        from google.cloud import storage
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_path)
        blob.upload_from_string(ndjson, content_type="application/x-ndjson")
    except Exception as e:
        logger.warning(f"GCS archive upload failed: {e}")
        _log_action("archive_upload", "failure", len(rows))
        return 0

    with _lock:
        _stats["archived"] += len(rows)
        _stats["archive_runs"] += 1
    _log_action("archive_to_cold", "success", len(rows))
    logger.info(f"Archived {len(rows)} events to gs://{bucket_name}/{blob_path}")
    return len(rows)


def _serialize_row(row: dict) -> str:
    """Serialize a BigQuery row to JSON, handling datetime objects."""
    clean = {}
    for k, v in row.items():
        if isinstance(v, datetime):
            clean[k] = v.isoformat()
        else:
            clean[k] = v
    return json.dumps(clean)


def _get_all_customer_ids() -> list[str]:
    """Return all known customer IDs from config files."""
    try:
        from src.customers.manager import list_customers
        return [c["customer_id"] for c in list_customers() if c.get("customer_id")]
    except Exception:
        return []


def archive_loop(interval: int = 3600):
    """Background thread: archive aged events to GCS cold tier.
    Iterates over all customers plus the shared dataset.
    """
    logger.info(f"Retention archiver started (every {interval}s)")
    while not _stop.is_set():
        try:
            # Archive shared dataset (no customer_id)
            archive_to_cold("")
            # Archive each customer's dataset
            for cid in _get_all_customer_ids():
                if _stop.is_set():
                    break
                archive_to_cold(cid)
        except Exception as e:
            logger.error(f"Archive loop error: {e}")
        _stop.wait(interval)


def stop():
    """Signal the archive loop to stop."""
    _stop.set()


def get_stats() -> dict:
    """Return archival statistics."""
    return dict(_stats)


def get_audit_log() -> list[dict]:
    """ALCOA+ audit trail for retention operations."""
    return list(reversed(_audit_log))


def _log_action(action: str, status: str, event_count: int):
    """Record an audit log entry."""
    _audit_log.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "status": status,
        "event_count": event_count,
    })
