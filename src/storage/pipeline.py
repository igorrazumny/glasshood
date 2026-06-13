# File: src/storage/pipeline.py
# Purpose: Stream ingested events to BigQuery with local buffer fallback

import collections
import json
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from src.config.settings import (
    STORAGE_ENABLED, STORAGE_BQ_PROJECT, STORAGE_BQ_DATASET,
    STORAGE_BQ_TABLE, STORAGE_LOCAL_DIR, STORAGE_FLUSH_INTERVAL,
)
from src.storage.customer_routing import (
    get_dataset_for_customer, get_table_ref_for_customer,
    group_events_by_customer,
)
from src.storage.encryption import encrypt_row

logger = logging.getLogger(__name__)

_buffer: collections.deque = collections.deque(maxlen=10000)
_lock = threading.Lock()
_audit_log: collections.deque = collections.deque(maxlen=500)
_stats = {"buffered": 0, "flushed_bq": 0, "failed": 0}
_stop = threading.Event()
# F-007: Singleton guard — prevent duplicate flush threads across workers
_flush_started = False
_flush_lock = threading.Lock()

# BigQuery table schema fields
BQ_SCHEMA = [
    {"name": "event_id", "type": "STRING", "mode": "REQUIRED"},
    {"name": "timestamp", "type": "TIMESTAMP", "mode": "REQUIRED"},
    {"name": "source_id", "type": "STRING", "mode": "REQUIRED"},
    {"name": "source_type", "type": "STRING", "mode": "NULLABLE"},
    {"name": "severity", "type": "STRING", "mode": "NULLABLE"},
    {"name": "message", "type": "STRING", "mode": "NULLABLE"},
    {"name": "agent_id", "type": "STRING", "mode": "NULLABLE"},
    {"name": "customer_id", "type": "STRING", "mode": "NULLABLE"},
    {"name": "tags", "type": "STRING", "mode": "NULLABLE"},
    {"name": "ingested_at", "type": "TIMESTAMP", "mode": "REQUIRED"},
]


def buffer_events(events: list[dict]) -> int:
    """Accept events from processor, enrich with IDs, buffer for flush."""
    if not STORAGE_ENABLED:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    count = 0
    with _lock:
        for event in events:
            row = {
                "event_id": str(uuid.uuid4()),
                "timestamp": event.get("timestamp", now),
                "source_id": event.get("source_id", ""),
                "source_type": event.get("source_type", ""),
                "severity": event.get("severity", "info"),
                "message": event.get("message", ""),
                "agent_id": event.get("agent_id", ""),
                "customer_id": event.get("customer_id", ""),
                "tags": json.dumps(event.get("tags", {})),
                "ingested_at": now,
            }
            _buffer.append(encrypt_row(row))
            count += 1
        _stats["buffered"] += count
    return count


def flush_to_bigquery() -> int:
    """Drain buffer and insert into BigQuery, routing by customer_id."""
    if not STORAGE_ENABLED:
        return 0
    # F-008: Refuse to flush/spool when BQ is not configured
    if not STORAGE_BQ_PROJECT:
        logger.warning("STORAGE_BQ_PROJECT not set — storage pipeline disabled, not spooling")
        return 0
    with _lock:
        rows = list(_buffer)
        _buffer.clear()
    if not rows:
        return _retry_spool()

    try:
        from google.cloud import bigquery
        client = bigquery.Client(project=STORAGE_BQ_PROJECT)
    except Exception as e:
        logger.warning(f"BigQuery client init failed, spooling locally: {e}")
        _spool_to_disk(rows)
        _stats["failed"] += len(rows)
        _log_action("flush_bq", "failure", len(rows))
        return 0

    # Route events to per-customer datasets
    groups = group_events_by_customer(rows)
    total_flushed = 0
    for cid, group_rows in groups.items():
        table_ref = get_table_ref_for_customer(cid)
        try:
            # F-005: Use event_id as insertId for idempotent inserts
            row_ids = [r.get("event_id", str(uuid.uuid4())) for r in group_rows]
            errors = client.insert_rows_json(table_ref, group_rows, row_ids=row_ids)
            if errors:
                logger.warning(f"BigQuery insert errors for customer '{cid}': {errors}")
                failed_indices = {e.get("index", i) for i, e in enumerate(errors)}
                failed_rows = [group_rows[i] for i in sorted(failed_indices) if i < len(group_rows)]
                if failed_rows:
                    _spool_to_disk(failed_rows)
                _stats["failed"] += len(failed_rows)
                flushed = len(group_rows) - len(failed_rows)
                _stats["flushed_bq"] += flushed
                total_flushed += flushed
                _log_action("flush_bq", "partial_failure", len(group_rows))
            else:
                _stats["flushed_bq"] += len(group_rows)
                total_flushed += len(group_rows)
                _log_action("flush_bq", "success", len(group_rows))
                logger.debug(f"Flushed {len(group_rows)} events to {table_ref}")
        except Exception as e:
            logger.warning(f"BigQuery flush failed for customer '{cid}', spooling: {e}")
            _spool_to_disk(group_rows)
            _stats["failed"] += len(group_rows)
            _log_action("flush_bq", "failure", len(group_rows))

    _retry_spool()
    return total_flushed


def _spool_to_disk(rows: list[dict]):
    """Write rows to local spool dir as JSON (crash-safe fallback)."""
    spool = Path(STORAGE_LOCAL_DIR)
    spool.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    uid = uuid.uuid4().hex[:8]
    filepath = spool / f"batch-{ts}-{uid}.json"
    filepath.write_text(json.dumps(rows))
    logger.info(f"Spooled {len(rows)} events to {filepath.name}")


def _retry_spool() -> int:
    """Re-attempt flushing previously spooled files, routing by customer_id."""
    spool = Path(STORAGE_LOCAL_DIR)
    if not spool.exists():
        return 0
    files = sorted(spool.glob("batch-*.json"))
    if not files:
        return 0
    try:
        from google.cloud import bigquery
        client = bigquery.Client(project=STORAGE_BQ_PROJECT)
    except Exception:
        return 0
    flushed = 0
    for f in files:
        try:
            rows = json.loads(f.read_text())
            groups = group_events_by_customer(rows)
            all_ok = True
            for cid, group_rows in groups.items():
                table_ref = get_table_ref_for_customer(cid)
                errors = client.insert_rows_json(table_ref, group_rows)
                if errors:
                    all_ok = False
                    break
            if all_ok:
                f.unlink()
                flushed += len(rows)
            else:
                break
        except Exception:
            break
    if flushed:
        _stats["flushed_bq"] += flushed
        _log_action("retry_spool", "success", flushed)
    return flushed


def ensure_table(customer_id: str = "") -> bool:
    """Create BigQuery dataset and table if not exists. Idempotent.
    Routes to per-customer dataset when customer_id is provided.
    """
    if not STORAGE_ENABLED or not STORAGE_BQ_PROJECT:
        return False
    try:
        from google.cloud import bigquery
        client = bigquery.Client(project=STORAGE_BQ_PROJECT)
        dataset_name = get_dataset_for_customer(customer_id)
        dataset_ref = bigquery.DatasetReference(STORAGE_BQ_PROJECT, dataset_name)
        try:
            client.get_dataset(dataset_ref)
        except Exception:
            dataset = bigquery.Dataset(dataset_ref)
            client.create_dataset(dataset)
            logger.info(f"Created BigQuery dataset: {dataset_name}")

        table_ref = dataset_ref.table(STORAGE_BQ_TABLE)
        try:
            client.get_table(table_ref)
        except Exception:
            schema = [
                bigquery.SchemaField(f["name"], f["type"], mode=f["mode"])
                for f in BQ_SCHEMA
            ]
            table = bigquery.Table(table_ref, schema=schema)
            # GxP: no partition expiration — never auto-delete production data
            table.time_partitioning = bigquery.TimePartitioning(
                field="timestamp",
            )
            table.require_partition_filter = True
            client.create_table(table)
            logger.info(f"Created BigQuery table: {dataset_name}.{STORAGE_BQ_TABLE}")
        return True
    except Exception as e:
        logger.warning(f"Failed to ensure BigQuery table: {e}")
        return False


def flush_loop(interval: int = None):
    """Background thread: flush buffer to BigQuery at interval.
    F-007: Singleton — only one flush thread runs per process.
    """
    global _flush_started
    with _flush_lock:
        if _flush_started:
            logger.warning("flush_loop already running — skipping duplicate start")
            return
        _flush_started = True
    if interval is None:
        interval = STORAGE_FLUSH_INTERVAL
    logger.info(f"Storage pipeline started (flush every {interval}s)")
    while not _stop.is_set():
        try:
            flush_to_bigquery()
        except Exception as e:
            logger.error(f"Pipeline flush error: {e}")
        _stop.wait(interval)


def stop():
    """Signal the flush loop to stop and reset singleton guard."""
    global _flush_started
    _stop.set()
    with _flush_lock:
        _flush_started = False


def get_stats() -> dict:
    """Return pipeline statistics."""
    return dict(_stats)


def get_audit_log() -> list[dict]:
    """ALCOA+ audit trail for storage pipeline."""
    return list(reversed(_audit_log))


def _log_action(action: str, status: str, event_count: int):
    """Record an audit log entry."""
    _audit_log.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "status": status,
        "event_count": event_count,
    })
