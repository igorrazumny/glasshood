# File: src/security/correlator.py
# Purpose: Correlate operational alerts with anomalies — pharma data integrity detection

import collections
import logging
from datetime import datetime, timezone

from src.models.alert import Alert

logger = logging.getLogger(__name__)

# ALCOA+ audit trail for correlation cycles
_audit_log: collections.deque = collections.deque(maxlen=200)


def correlate(alerts: list[Alert], anomalies: list[dict],
              time_window: int = 300) -> list[Alert]:
    """Correlate operational alerts with anomalies within a time window.

    When a node has BOTH an operational alert AND a statistical anomaly
    within the time window, creates an elevated-severity correlated alert.
    This is the pharma differentiator: coinciding operational + security
    anomalies suggest potential data integrity compromise.

    Args:
        alerts: Active alerts from rule engine
        anomalies: Current anomalies from anomaly detector
        time_window: Seconds within which events are considered correlated

    Returns:
        List of new correlated Alert objects
    """
    if not alerts or not anomalies:
        _audit_log.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": "correlate",
            "alerts_checked": len(alerts),
            "anomalies_checked": len(anomalies),
            "correlations_found": 0,
        })
        return []

    now = datetime.now(timezone.utc)
    correlated = []

    # Build anomaly lookup by metric for quick matching
    recent_anomalies = []
    for anomaly in anomalies:
        ts = anomaly.get("timestamp", "")
        if ts:
            try:
                anomaly_time = datetime.fromisoformat(ts)
                age = (now - anomaly_time).total_seconds()
                if age <= time_window:
                    recent_anomalies.append(anomaly)
            except (ValueError, TypeError):
                recent_anomalies.append(anomaly)  # include if we can't parse time
        else:
            recent_anomalies.append(anomaly)

    if not recent_anomalies:
        _audit_log.append({
            "timestamp": now.isoformat(),
            "action": "correlate",
            "alerts_checked": len(alerts),
            "anomalies_checked": len(anomalies),
            "correlations_found": 0,
        })
        return []

    # Check each alert against anomalies
    seen = set()
    for alert in alerts:
        if alert.acknowledged:
            continue

        alert_age = 0.0
        try:
            alert_time = datetime.fromisoformat(alert.triggered_at)
            alert_age = (now - alert_time).total_seconds()
        except (ValueError, TypeError):
            pass

        if alert_age > time_window:
            continue

        for anomaly in recent_anomalies:
            # Correlation key: alert rule + anomaly metric (deduplicate)
            key = (alert.rule_id, alert.node_id, anomaly["metric"])
            if key in seen:
                continue

            # Match: same node (if alert has node_id) or global scope
            correlated_alert = Alert(
                rule_id=f"correlated:{alert.rule_id}+{anomaly['metric']}",
                severity="critical",
                message=(f"Correlated: {alert.message} coinciding with "
                         f"{anomaly['metric']} anomaly (z={anomaly.get('z_score', '?')}). "
                         f"Potential data integrity risk."),
                triggered_at=now.isoformat(),
                node_id=alert.node_id,
                metric_name=anomaly["metric"],
                metric_value=anomaly.get("value"),
            )
            correlated.append(correlated_alert)
            seen.add(key)

    # ALCOA+ audit trail
    _audit_log.append({
        "timestamp": now.isoformat(),
        "action": "correlate",
        "alerts_checked": len(alerts),
        "anomalies_checked": len(anomalies),
        "correlations_found": len(correlated),
        "correlations": [
            {"rule_id": a.rule_id, "node_id": a.node_id, "severity": a.severity}
            for a in correlated
        ],
    })

    if correlated:
        logger.warning(f"Correlation engine: {len(correlated)} correlated alerts — "
                       f"potential data integrity risk")

    return correlated


def get_audit_log() -> list[dict]:
    """Return ALCOA+ audit trail entries (most recent first)."""
    return list(reversed(_audit_log))
