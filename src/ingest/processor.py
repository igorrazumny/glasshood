# File: src/ingest/processor.py
# Purpose: Process and store ingested events from remote agents

import collections
import logging
import threading
from datetime import datetime, timezone

from src.models.ingest_event import VALID_SOURCE_TYPES, VALID_SEVERITIES

logger = logging.getLogger(__name__)

_events: collections.deque = collections.deque(maxlen=5000)
_agent_heartbeats: dict = {}  # agent_id -> {last_seen, event_count, ...}
_lock = threading.Lock()
_audit_log: collections.deque = collections.deque(maxlen=500)


def _validate_event(event: dict) -> str | None:
    """Validate a single event dict. Returns error message or None."""
    if not event.get("source_id"):
        return "missing source_id"
    if not event.get("message"):
        return "missing message"
    if event.get("source_type", "file") not in VALID_SOURCE_TYPES:
        return f"invalid source_type: {event.get('source_type')}"
    if event.get("severity", "info") not in VALID_SEVERITIES:
        return f"invalid severity: {event.get('severity')}"
    return None


def process_batch(events: list[dict], agent_id: str) -> dict:
    """Validate and store a batch of events. Returns {accepted, rejected, errors}."""
    now = datetime.now(timezone.utc).isoformat()
    accepted = 0
    rejected = 0
    errors = []

    with _lock:
        for event in events:
            error = _validate_event(event)
            if error:
                rejected += 1
                errors.append(error)
                continue
            # Fill defaults
            event.setdefault("timestamp", now)
            event.setdefault("severity", "info")
            event.setdefault("source_type", "file")
            event["agent_id"] = agent_id
            _events.append(event)
            accepted += 1

        # Update heartbeat
        hb = _agent_heartbeats.get(agent_id, {"total_events": 0})
        hb["last_seen"] = now
        hb["total_events"] = hb.get("total_events", 0) + accepted
        _agent_heartbeats[agent_id] = hb

    _audit_log.append({
        "timestamp": now,
        "action": "batch_processed",
        "agent_id": agent_id,
        "accepted": accepted,
        "rejected": rejected,
    })
    logger.info(f"Ingest batch from {agent_id}: {accepted} accepted, {rejected} rejected")

    # Feed accepted events to rules engine and storage pipeline
    if accepted > 0:
        _feed_to_rules(events)
        _feed_to_storage(events)

    return {"accepted": accepted, "rejected": rejected, "errors": errors}


def record_heartbeat(agent_id: str, status: dict):
    """Record a heartbeat from an agent."""
    now = datetime.now(timezone.utc).isoformat()
    with _lock:
        hb = _agent_heartbeats.get(agent_id, {"total_events": 0})
        hb["last_seen"] = now
        hb.update({k: v for k, v in status.items() if k != "total_events"})
        _agent_heartbeats[agent_id] = hb


def get_recent_events(limit: int = 100, source_type: str = None) -> list[dict]:
    """Return recent events, optionally filtered by source_type."""
    with _lock:
        events = list(reversed(_events))
    if source_type:
        events = [e for e in events if e.get("source_type") == source_type]
    return events[:limit]


def get_agent_status() -> dict:
    """Return heartbeat status for all known agents."""
    with _lock:
        return dict(_agent_heartbeats)


def _feed_to_rules(events: list[dict]):
    """Convert ingested events to a snapshot for the rules engine."""
    from src.config.settings import INGEST_RULES_ENABLED
    if not INGEST_RULES_ENABLED:
        return
    snapshot = {}
    for source_type in ("file", "syslog", "webhook"):
        type_events = [e for e in events if e.get("source_type") == source_type]
        error_count = sum(1 for e in type_events
                          if e.get("severity") in ("error", "critical", "emergency", "alert"))
        snapshot[f"ingest_{source_type}"] = {
            "event_count": len(type_events),
            "error_count": error_count,
        }
    try:
        from src.rules.engine import evaluate_rules
        evaluate_rules([], snapshot)
    except Exception as e:
        logger.warning(f"Rules evaluation on ingest failed: {e}")


def _feed_to_storage(events: list[dict]):
    """Feed accepted events to storage pipeline for BigQuery persistence."""
    from src.config.settings import STORAGE_ENABLED
    if not STORAGE_ENABLED:
        return
    try:
        from src.storage.pipeline import buffer_events
        buffer_events(events)
    except Exception as e:
        logger.warning(f"Storage pipeline feed failed: {e}")


def get_audit_log() -> list[dict]:
    """ALCOA+ audit trail for ingestion."""
    return list(reversed(_audit_log))
