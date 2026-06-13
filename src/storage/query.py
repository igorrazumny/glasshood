# File: src/storage/query.py
# Purpose: Cross-tier query interface for stored events

import logging
from datetime import datetime, timezone, timedelta

from src.config.settings import (
    STORAGE_ENABLED, STORAGE_BQ_PROJECT, STORAGE_BQ_DATASET,
    STORAGE_BQ_TABLE, RETENTION_ARCHIVE_BUCKET,
)
from src.storage.customer_routing import (
    get_table_ref_for_customer, get_bucket_for_customer,
)
from src.storage.encryption import decrypt_row

logger = logging.getLogger(__name__)


def query_hot(source_id: str = None, severity: str = None,
              limit: int = 100, hours: int = 168,
              customer_id: str = None) -> list[dict]:
    """Query BigQuery for recent events (hot tier, default 7 days)."""
    if not STORAGE_ENABLED or not STORAGE_BQ_PROJECT:
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    return _query_bq(source_id, severity, limit, cutoff, None,
                     customer_id=customer_id)


def query_warm(source_id: str = None, severity: str = None,
               limit: int = 100, start_date: str = None,
               end_date: str = None, customer_id: str = None) -> list[dict]:
    """Query BigQuery for older events (warm tier)."""
    if not STORAGE_ENABLED or not STORAGE_BQ_PROJECT:
        return []
    start = datetime.fromisoformat(start_date) if start_date else None
    end = datetime.fromisoformat(end_date) if end_date else None
    return _query_bq(source_id, severity, limit, start, end,
                     customer_id=customer_id)


def _query_bq(source_id: str, severity: str, limit: int,
              start: datetime = None, end: datetime = None,
              customer_id: str = None) -> list[dict]:
    """Parameterized BigQuery query."""
    try:
        from google.cloud import bigquery
        client = bigquery.Client(project=STORAGE_BQ_PROJECT)
        table_ref = get_table_ref_for_customer(customer_id or "")

        conditions = []
        params = []

        # F-004: Use explicit timestamp bounds for partition filter compliance
        if start:
            conditions.append("timestamp >= @start_time")
            params.append(bigquery.ScalarQueryParameter(
                "start_time", "TIMESTAMP", start.isoformat()))
        else:
            # Default: last 90 days as explicit bound (satisfies require_partition_filter)
            default_start = datetime.now(timezone.utc) - timedelta(days=90)
            conditions.append("timestamp >= @start_time")
            params.append(bigquery.ScalarQueryParameter(
                "start_time", "TIMESTAMP", default_start.isoformat()))
        if end:
            conditions.append("timestamp < @end_time")
            params.append(bigquery.ScalarQueryParameter(
                "end_time", "TIMESTAMP", end.isoformat()))
        if source_id:
            conditions.append("source_id = @source_id")
            params.append(bigquery.ScalarQueryParameter(
                "source_id", "STRING", source_id))
        if severity:
            conditions.append("severity = @severity")
            params.append(bigquery.ScalarQueryParameter(
                "severity", "STRING", severity))
        if customer_id:
            conditions.append("customer_id = @customer_id")
            params.append(bigquery.ScalarQueryParameter(
                "customer_id", "STRING", customer_id))

        where = " AND ".join(conditions)
        query = f"SELECT * FROM `{table_ref}` WHERE {where} ORDER BY timestamp DESC LIMIT {int(limit)}"

        job_config = bigquery.QueryJobConfig(query_parameters=params)
        result = client.query(query, job_config=job_config)
        rows = []
        for row in result:
            r = dict(row)
            for k, v in r.items():
                if isinstance(v, datetime):
                    r[k] = v.isoformat()
            rows.append(decrypt_row(r))
        return rows
    except Exception as e:
        logger.warning(f"BigQuery query failed: {e}")
        return []


def list_cold_archives(prefix: str = None, customer_id: str = "") -> list[dict]:
    """List GCS cold archive blobs (metadata only)."""
    bucket_name = get_bucket_for_customer(customer_id)
    if not bucket_name:
        return []
    try:
        from google.cloud import storage
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob_prefix = prefix or "glasshood-archive/"
        blobs = bucket.list_blobs(prefix=blob_prefix, max_results=1000)
        return [
            {"name": b.name, "size": b.size, "updated": b.updated.isoformat() if b.updated else ""}
            for b in blobs
        ]
    except Exception as e:
        logger.warning(f"GCS archive listing failed: {e}")
        return []
