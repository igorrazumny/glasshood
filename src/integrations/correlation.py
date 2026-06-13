# File: src/integrations/correlation.py
# Purpose: Correlate GlassHood alerts with ServiceNow incidents and change tickets
#
# Three functions:
#   correlate_with_incidents() — match alerts to SNOW incidents by node + time window
#   correlate_with_changes()   — match alerts to SNOW changes (causality: change BEFORE alert)
#   surface_patterns()         — group by node, count incidents over rolling window
#
# All inputs are plain dicts (decoupled from live modules — testable without mocks).
# ALCOA+ audit trail in _audit_log deque.

import collections
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_audit_log: collections.deque = collections.deque(maxlen=500)


def _parse_iso(ts: str) -> Optional[datetime]:
    """Parse ISO timestamp, return None on failure."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def correlate_with_incidents(
    alerts: list[dict],
    incidents: list[dict],
    node_to_cmdb: dict,
    time_window_seconds: int = 1800,
) -> list[dict]:
    """Match GlassHood alerts to SNOW incidents by system + time window.

    - alert.node_id maps to SNOW cmdb_ci via node_to_cmdb config
    - If node_to_cmdb empty: correlate on timestamp only (no system filter)
    - Timestamps within time_window_seconds = correlated

    Returns list of correlation dicts.
    """
    now = datetime.now(timezone.utc)
    correlations = []

    for alert in alerts:
        alert_time = _parse_iso(alert.get("triggered_at", ""))
        if not alert_time:
            continue
        node_id = alert.get("node_id", "")
        cmdb_ci = node_to_cmdb.get(node_id, "") if node_to_cmdb else ""

        for incident in incidents:
            if cmdb_ci and incident.get("cmdb_ci") != cmdb_ci:
                continue

            inc_time = _parse_iso(incident.get("opened_at", ""))
            if not inc_time:
                continue

            delta = abs((alert_time - inc_time).total_seconds())
            if delta <= time_window_seconds:
                correlations.append({
                    "type": "alert_incident",
                    "alert_rule_id": alert.get("rule_id"),
                    "alert_node_id": node_id,
                    "alert_severity": alert.get("severity"),
                    "alert_time": alert.get("triggered_at"),
                    "snow_sys_id": incident.get("sys_id"),
                    "snow_number": incident.get("number"),
                    "snow_description": incident.get("short_description", ""),
                    "delta_seconds": round(delta),
                    "correlated_at": now.isoformat(),
                })

    _audit_log.append({
        "timestamp": now.isoformat(),
        "action": "correlate_incidents",
        "alerts_checked": len(alerts),
        "incidents_checked": len(incidents),
        "correlations_found": len(correlations),
    })
    return correlations


def correlate_with_changes(
    alerts: list[dict],
    changes: list[dict],
    node_to_cmdb: dict,
    lookback_seconds: int = 3600,
) -> list[dict]:
    """Match GlassHood alerts to SNOW changes where change PRECEDES alert.

    Causality direction: change at T -> alert at T+N where 0 < N <= lookback_seconds.
    "Firewall change at 02:45, timeout alert at 03:14" — automatically linked.

    confidence: "high" if delta < 900s (15 min), "medium" otherwise.
    """
    now = datetime.now(timezone.utc)
    correlations = []

    for alert in alerts:
        alert_time = _parse_iso(alert.get("triggered_at", ""))
        if not alert_time:
            continue
        node_id = alert.get("node_id", "")
        cmdb_ci = node_to_cmdb.get(node_id, "") if node_to_cmdb else ""

        for change in changes:
            if cmdb_ci and change.get("cmdb_ci") != cmdb_ci:
                continue

            change_time = _parse_iso(change.get("start_date", ""))
            if not change_time:
                continue

            # Change must precede alert (positive delta = change happened first)
            delta = (alert_time - change_time).total_seconds()
            if 0 < delta <= lookback_seconds:
                correlations.append({
                    "type": "change_caused_alert",
                    "alert_rule_id": alert.get("rule_id"),
                    "alert_node_id": node_id,
                    "alert_severity": alert.get("severity"),
                    "alert_time": alert.get("triggered_at"),
                    "snow_sys_id": change.get("sys_id"),
                    "snow_number": change.get("number"),
                    "snow_description": change.get("short_description", ""),
                    "change_time": change.get("start_date"),
                    "delta_seconds": round(delta),
                    "cause_confidence": "high" if delta < 900 else "medium",
                    "correlated_at": now.isoformat(),
                })

    _audit_log.append({
        "timestamp": now.isoformat(),
        "action": "correlate_changes",
        "alerts_checked": len(alerts),
        "changes_checked": len(changes),
        "correlations_found": len(correlations),
    })
    return correlations


def surface_patterns(
    incident_correlations: list[dict],
    change_correlations: list[dict],
) -> list[dict]:
    """Surface patterns across correlations.

    Groups by node_id, counts distinct SNOW tickets.
    Surfaces nodes with >= 2 distinct tickets (possible systemic issue).
    Returns list sorted by ticket count descending.
    """
    node_incidents: dict[str, set] = collections.defaultdict(set)
    node_changes: dict[str, set] = collections.defaultdict(set)

    for c in incident_correlations:
        n = c.get("alert_node_id", "unknown")
        node_incidents[n].add(c.get("snow_sys_id", ""))

    for c in change_correlations:
        n = c.get("alert_node_id", "unknown")
        node_changes[n].add(c.get("snow_sys_id", ""))

    all_nodes = set(node_incidents) | set(node_changes)
    patterns = []
    for node in all_nodes:
        inc_count = len(node_incidents.get(node, set()))
        chg_count = len(node_changes.get(node, set()))
        if inc_count + chg_count < 2:
            continue
        patterns.append({
            "node_id": node,
            "incident_ticket_count": inc_count,
            "change_ticket_count": chg_count,
            "total_ticket_count": inc_count + chg_count,
            "pattern_type": ("repeated_incidents" if inc_count >= 2
                             else "change_induced_incidents"),
            "significance": "high" if (inc_count + chg_count) >= 3 else "medium",
        })

    patterns.sort(key=lambda p: p["total_ticket_count"], reverse=True)

    _audit_log.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": "surface_patterns",
        "nodes_analyzed": len(all_nodes),
        "patterns_found": len(patterns),
    })
    return patterns


def get_audit_log() -> list[dict]:
    """Return ALCOA+ audit trail (most recent first)."""
    return list(reversed(_audit_log))
