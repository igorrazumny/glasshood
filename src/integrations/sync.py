# File: src/integrations/sync.py
# Purpose: Bi-directional SNOW<->GlassHood sync
#   - Push new GlassHood alerts to SNOW as incidents (outbound)
#   - Poll SNOW for resolved incidents, auto-acknowledge GlassHood alerts (inbound)
#   - Run correlation cycle and cache results
#
# Sync state is in-memory. SNOW is the system of record.
# Pattern: mirrors gcs_bucket.poll_loop() with threading.Event stop pattern.

import collections
import logging
import threading
import time
from datetime import datetime, timezone, timedelta

from src.config.settings import (
    SNOW_INSTANCE_URL, SNOW_USERNAME, SNOW_PASSWORD, SNOW_ENABLED,
)
from src.integrations.servicenow import ServiceNowClient, _load_config
from src.integrations.correlation import (
    correlate_with_incidents, correlate_with_changes, surface_patterns,
)

logger = logging.getLogger(__name__)

_sync_state: dict = {}  # key = "rule_id:node_id" -> {"snow_sys_id", "synced_at"}
_lock = threading.Lock()
_last_sync: float = 0

_correlation_results: dict = {
    "incident_correlations": [],
    "change_correlations": [],
    "patterns": [],
    "timestamp": None,
}

_audit_log: collections.deque = collections.deque(maxlen=500)


def _get_client(config: dict) -> ServiceNowClient:
    """Build a ServiceNowClient from env + config."""
    return ServiceNowClient(
        instance_url=SNOW_INSTANCE_URL or config.get("instance_url", ""),
        username=SNOW_USERNAME,
        password=SNOW_PASSWORD,
    )


def _build_incident_payload(alert: dict, severity_map: dict) -> dict:
    """Map a GlassHood alert to a SNOW incident payload."""
    severity = alert.get("severity", "warning")
    mapping = severity_map.get(severity, {"urgency": 2, "impact": 2})
    return {
        "short_description": f"GlassHood: {alert.get('message', alert.get('rule_id', 'alert'))}",
        "description": (
            f"Rule: {alert.get('rule_id')}\n"
            f"Node: {alert.get('node_id', 'N/A')}\n"
            f"Metric: {alert.get('metric_name', 'N/A')} = {alert.get('metric_value', 'N/A')}\n"
            f"Triggered: {alert.get('triggered_at')}\n"
            f"Source: GlassHood automated monitoring"
        ),
        "urgency": str(mapping["urgency"]),
        "impact": str(mapping["impact"]),
        "category": "Software",
        "subcategory": "Infrastructure Monitoring",
    }


def push_alerts_to_snow(alerts: list[dict], client: ServiceNowClient,
                        config: dict) -> list[str]:
    """Push unsynced critical/warning alerts to SNOW. Returns new sys_ids."""
    severity_map = config.get("severity_map", {})
    new_sys_ids = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for alert in alerts:
        if alert.get("acknowledged"):
            continue
        if alert.get("severity", "info") not in ("critical", "warning"):
            continue

        key = f"{alert.get('rule_id', '')}:{alert.get('node_id', '')}"
        with _lock:
            if key in _sync_state:
                continue

        payload = _build_incident_payload(alert, severity_map)
        sys_id = client.create_incident(payload)
        if sys_id:
            with _lock:
                _sync_state[key] = {"snow_sys_id": sys_id, "synced_at": now_iso}
            new_sys_ids.append(sys_id)
            _audit_log.append({
                "timestamp": now_iso,
                "action": "push_to_snow",
                "rule_id": alert.get("rule_id"),
                "node_id": alert.get("node_id"),
                "snow_sys_id": sys_id,
            })
            logger.info(f"Pushed alert {key} to SNOW as {sys_id}")

    return new_sys_ids


def pull_resolved_from_snow(client: ServiceNowClient, config: dict) -> list[str]:
    """Check SNOW for resolved incidents. Auto-ack matching GlassHood alerts."""
    resolved_states = config.get("resolved_states", ["6", "7"])
    fields = ["sys_id", "state", "resolved_at"]
    since = (datetime.now(timezone.utc) - timedelta(minutes=60)).isoformat()
    incidents = client.fetch_incidents(since, fields, limit=200)

    resolved_sys_ids = {
        inc["sys_id"] for inc in incidents
        if inc.get("state") in resolved_states
    }

    auto_acked = []
    now_iso = datetime.now(timezone.utc).isoformat()

    with _lock:
        synced_items = list(_sync_state.items())

    for key, state in synced_items:
        if state["snow_sys_id"] in resolved_sys_ids:
            rule_id, _, node_id = key.partition(":")
            try:
                from src.rules.engine import acknowledge_alert
                found = acknowledge_alert(rule_id, node_id or None, "servicenow-sync")
                if found:
                    auto_acked.append(key)
                    _audit_log.append({
                        "timestamp": now_iso,
                        "action": "auto_ack_from_snow",
                        "rule_id": rule_id,
                        "node_id": node_id,
                        "snow_sys_id": state["snow_sys_id"],
                    })
            except Exception as e:
                logger.warning(f"Auto-ack failed for {key}: {e}")

    return auto_acked


def run_correlation_cycle(alerts: list[dict], client: ServiceNowClient,
                          config: dict) -> dict:
    """Fetch SNOW tickets and run full correlation cycle."""
    global _correlation_results

    time_window = config.get("time_window_seconds", 1800)
    change_lookback = config.get("change_lookback_seconds", 3600)
    node_to_cmdb = config.get("node_to_cmdb", {})
    inc_fields = config.get("incident_fields",
                            ["sys_id", "number", "short_description", "state",
                             "opened_at", "cmdb_ci"])
    chg_fields = config.get("change_fields",
                            ["sys_id", "number", "short_description", "state",
                             "start_date", "cmdb_ci"])

    since_inc = (datetime.now(timezone.utc) - timedelta(seconds=time_window * 2)).isoformat()
    since_chg = (datetime.now(timezone.utc) - timedelta(seconds=change_lookback)).isoformat()

    incidents = client.fetch_incidents(since_inc, inc_fields)
    changes = client.fetch_changes(since_chg, chg_fields)

    inc_corrs = correlate_with_incidents(alerts, incidents, node_to_cmdb, time_window)
    chg_corrs = correlate_with_changes(alerts, changes, node_to_cmdb, change_lookback)
    patterns = surface_patterns(inc_corrs, chg_corrs)

    result = {
        "incident_correlations": inc_corrs,
        "change_correlations": chg_corrs,
        "patterns": patterns,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    _correlation_results = result
    return result


def sync_once():
    """Run one full sync cycle: push alerts, pull resolved, correlate."""
    global _last_sync
    if not SNOW_ENABLED:
        return

    config = _load_config()
    if not config.get("enabled", False):
        return

    client = _get_client(config)
    now_iso = datetime.now(timezone.utc).isoformat()

    try:
        from src.rules.engine import get_alerts
        alerts = get_alerts()

        push_alerts_to_snow(alerts, client, config)
        pull_resolved_from_snow(client, config)
        run_correlation_cycle(alerts, client, config)

        _last_sync = time.time()
        _audit_log.append({
            "timestamp": now_iso,
            "action": "sync_cycle",
            "alerts_processed": len(alerts),
            "synced_items": len(_sync_state),
        })
    except Exception as e:
        logger.error(f"SNOW sync cycle failed: {e}")
        _audit_log.append({
            "timestamp": now_iso, "action": "sync_cycle_error",
            "error": str(e),
        })


def sync_loop(interval: int = 300):
    """Background sync loop — same pattern as gcs_bucket.poll_loop()."""
    stop = threading.Event()
    sync_once()
    while not stop.wait(interval):
        sync_once()


def get_correlation_results() -> dict:
    return dict(_correlation_results)


def get_sync_state() -> list[dict]:
    with _lock:
        return [
            {"key": k, "snow_sys_id": v["snow_sys_id"], "synced_at": v["synced_at"]}
            for k, v in _sync_state.items()
        ]


def get_audit_log() -> list[dict]:
    return list(reversed(_audit_log))
