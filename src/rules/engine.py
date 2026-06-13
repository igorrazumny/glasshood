# File: src/rules/engine.py
# Purpose: Layer 1 deterministic rule engine — threshold/condition checks, no AI

import collections
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from src.models.alert import Alert
from src.models.topology import Node

logger = logging.getLogger(__name__)

_alerts: list[Alert] = []
_lock = threading.Lock()
# Dedup window: same rule_id + node_id within this many seconds = skip
_DEDUP_WINDOW = 300  # 5 minutes
_ALERT_TTL = 3600  # alerts expire after 1 hour

# ALCOA+ audit trail — ring buffer of evaluation cycles
_audit_log: collections.deque = collections.deque(maxlen=500)

# Operator functions
_OPS = {
    ">": lambda v, t: v > t,
    ">=": lambda v, t: v >= t,
    "<": lambda v, t: v < t,
    "<=": lambda v, t: v <= t,
    "==": lambda v, t: v == t,
    "!=": lambda v, t: v != t,
}


def load_rules(path: str) -> list[dict]:
    """Load rule definitions from YAML. Returns empty list on error."""
    p = Path(path)
    if not p.exists():
        logger.warning(f"Rules config not found: {path}")
        return []
    try:
        with open(p) as f:
            data = yaml.safe_load(f) or {}
        rules = data.get("rules", [])
        logger.info(f"Loaded {len(rules)} rules from {path}")
        return rules
    except Exception as e:
        logger.error(f"Failed to load rules: {e}")
        return []


def _is_duplicate(rule_id: str, node_id: Optional[str], now: float) -> bool:
    """Check if an alert with same rule_id + node_id exists within dedup window."""
    for alert in _alerts:
        if (alert.rule_id == rule_id
                and alert.node_id == node_id
                and (now - datetime.fromisoformat(alert.triggered_at).timestamp()) < _DEDUP_WINDOW):
            return True
    return False


def _prune_expired(now: float) -> None:
    """Remove alerts older than TTL."""
    cutoff = now - _ALERT_TTL
    _alerts[:] = [a for a in _alerts
                  if datetime.fromisoformat(a.triggered_at).timestamp() > cutoff]


def _check_node_rule(rule: dict, node: Node) -> Optional[Alert]:
    """Evaluate a node-scoped rule against a single node."""
    cond = rule.get("condition", {})
    metric_name = cond.get("metric")
    if not metric_name:
        return None

    # Filter by node type if specified
    allowed_types = rule.get("node_types")
    if allowed_types and node.type not in allowed_types:
        return None

    # Get value: special case for "status" (check node.status), otherwise node.metrics
    if metric_name == "status":
        value = node.status
        target = cond.get("value")
        op_fn = _OPS.get(cond.get("operator", "=="))
        if op_fn and op_fn(value, target):
            return Alert(
                rule_id=rule["id"],
                severity=rule.get("severity", "warning"),
                message=f"{rule.get('description', rule['id'])}: {node.label} status={value}",
                triggered_at=datetime.now(timezone.utc).isoformat(),
                node_id=node.id,
                metric_name="status",
            )
        return None

    # Numeric metric check
    value = node.metrics.get(metric_name)
    if value is None:
        return None

    threshold = cond.get("threshold")
    if threshold is None:
        return None

    op_fn = _OPS.get(cond.get("operator", ">"))
    if not op_fn:
        return None

    try:
        if op_fn(float(value), float(threshold)):
            return Alert(
                rule_id=rule["id"],
                severity=rule.get("severity", "warning"),
                message=f"{rule.get('description', rule['id'])}: {node.label} {metric_name}={value}",
                triggered_at=datetime.now(timezone.utc).isoformat(),
                node_id=node.id,
                metric_name=metric_name,
                metric_value=float(value),
                threshold=float(threshold),
            )
    except (ValueError, TypeError):
        pass
    return None


def _check_global_rule(rule: dict, snapshot: dict) -> Optional[Alert]:
    """Evaluate a global-scoped rule against collector data."""
    cond = rule.get("condition", {})
    source = cond.get("source")
    metric_name = cond.get("metric")
    if not source or not metric_name:
        return None

    source_data = snapshot.get(source, {})
    value = source_data.get(metric_name)
    if value is None:
        return None

    threshold = cond.get("threshold")
    if threshold is None:
        return None

    op_fn = _OPS.get(cond.get("operator", ">"))
    if not op_fn:
        return None

    try:
        if op_fn(float(value), float(threshold)):
            # REQ-004: preserve the metric-detail message so webhooks/SIEM
            # consumers always see the rule description plus metric=value;
            # the classification title (if any) travels in a separate
            # anomaly_classification field on the Alert, not by overwriting
            # the message. classify_anomalies is wrapped — a malformed
            # anomaly never crashes evaluate_rule.
            message = f"{rule.get('description', rule['id'])}: {metric_name}={value}"
            classification: Optional[dict] = None
            if source == "anomaly":
                try:
                    from src.security.anomaly_detector import (
                        get_anomalies, classify_anomalies,
                    )
                    anomalies = get_anomalies()
                    if anomalies:
                        classification = classify_anomalies(anomalies)
                except Exception as e:
                    logger.warning(f"REQ-004: classify_anomalies failed for rule "
                                   f"{rule.get('id')!r}: {e}")
                    classification = None
            return Alert(
                rule_id=rule["id"],
                severity=rule.get("severity", "warning"),
                message=message,
                triggered_at=datetime.now(timezone.utc).isoformat(),
                metric_name=metric_name,
                metric_value=float(value),
                threshold=float(threshold),
                anomaly_classification=classification,
            )
    except (ValueError, TypeError):
        pass
    return None


def evaluate_rules(nodes: list, snapshot: dict,
                   rules_path: str = None) -> list[Alert]:
    """Evaluate all rules against current state. Returns new alerts (deduplicated)."""
    from src.config.settings import RULES_CONFIG_PATH
    if rules_path is None:
        rules_path = RULES_CONFIG_PATH

    rules = load_rules(rules_path)
    if not rules:
        return []

    now = time.time()
    new_alerts = []

    with _lock:
        _prune_expired(now)

        for rule in rules:
            scope = rule.get("scope", "node")

            if scope == "global":
                alert = _check_global_rule(rule, snapshot)
                if alert and not _is_duplicate(rule["id"], None, now):
                    _alerts.append(alert)
                    new_alerts.append(alert)

            else:  # node scope
                for node in nodes:
                    alert = _check_node_rule(rule, node)
                    if alert and not _is_duplicate(rule["id"], node.id, now):
                        _alerts.append(alert)
                        new_alerts.append(alert)

    if new_alerts:
        logger.info(f"Rule engine: {len(new_alerts)} new alerts "
                     f"({sum(1 for a in new_alerts if a.severity == 'critical')} critical)")

    # ALCOA+ audit trail: log every evaluation cycle
    _audit_log.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "rules_evaluated": len(rules),
        "nodes_checked": len(nodes),
        "alerts_new": len(new_alerts),
        "alerts_active": len(_alerts),
        "triggered": [
            {"rule_id": a.rule_id, "node_id": a.node_id,
             "severity": a.severity, "metric_name": a.metric_name,
             "metric_value": a.metric_value, "threshold": a.threshold}
            for a in new_alerts
        ],
    })

    return list(_alerts)


def get_alerts() -> list[dict]:
    """Return current active alerts as dicts."""
    now = time.time()
    with _lock:
        _prune_expired(now)
        return [a.to_dict() for a in _alerts]


def acknowledge_alert(rule_id: str, node_id: Optional[str], user: str) -> bool:
    """Acknowledge an alert. Returns True if found and acknowledged."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with _lock:
        for alert in _alerts:
            if alert.rule_id == rule_id and alert.node_id == node_id and not alert.acknowledged:
                alert.acknowledged = True
                alert.acknowledged_at = now_iso
                alert.acknowledged_by = user
                logger.info(f"Alert acknowledged: {rule_id} node={node_id} by={user}")
                _audit_log.append({
                    "timestamp": now_iso,
                    "action": "acknowledge",
                    "rule_id": rule_id,
                    "node_id": node_id,
                    "acknowledged_by": user,
                })
                return True
    return False


def get_audit_log() -> list[dict]:
    """Return ALCOA+ audit trail entries (most recent first)."""
    return list(reversed(_audit_log))
