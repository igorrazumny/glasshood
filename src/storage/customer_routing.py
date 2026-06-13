# File: src/storage/customer_routing.py
# Purpose: Per-customer BigQuery dataset and GCS bucket routing

import collections
import logging

from src.config.settings import (
    STORAGE_BQ_PROJECT, STORAGE_BQ_DATASET, STORAGE_BQ_TABLE,
    RETENTION_ARCHIVE_BUCKET,
)

logger = logging.getLogger(__name__)


def _sanitize_customer_id(customer_id: str) -> str:
    """Replace hyphens with underscores for BigQuery-safe dataset names."""
    return customer_id.replace("-", "_")


def get_dataset_for_customer(customer_id: str) -> str:
    """Return BQ dataset name: shared dataset if empty, else glasshood_{sanitized_id}."""
    if not customer_id:
        return STORAGE_BQ_DATASET
    return f"glasshood_{_sanitize_customer_id(customer_id)}"


def get_table_ref_for_customer(customer_id: str) -> str:
    """Return fully-qualified BQ table reference: project.dataset.table."""
    dataset = get_dataset_for_customer(customer_id)
    return f"{STORAGE_BQ_PROJECT}.{dataset}.{STORAGE_BQ_TABLE}"


def get_bucket_for_customer(customer_id: str) -> str:
    """Return GCS archive bucket name: shared bucket if empty, else glasshood-archive-{id}."""
    if not customer_id:
        return RETENTION_ARCHIVE_BUCKET
    return f"glasshood-archive-{customer_id}"


def group_events_by_customer(rows: list[dict]) -> dict[str, list[dict]]:
    """Group event rows by customer_id. Missing customer_id grouped under empty string."""
    groups: dict[str, list[dict]] = {}
    for row in rows:
        cid = row.get("customer_id", "")
        groups.setdefault(cid, []).append(row)
    return groups
