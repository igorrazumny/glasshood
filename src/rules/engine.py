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

_lock = threading.Lock()

# REQ-GHA-027: one alarm per (group, part) while its condition holds; when a checked
# condition no longer holds the alarm moves to the resolved list with its end time.
_active: dict[tuple, Alert] = {}
_resolved: collections.deque = collections.deque(maxlen=50)
_RESOLVED_KEEP_S = 24 * 3600
# A rule with no data for this long is listed as "not checked"
_NOT_CHECKED_AFTER_S = 3600
_rule_checked_at: dict[str, float] = {}
_rule_names: dict[str, str] = {}
_SEVERITY_RANK = {"critical": 3, "warning": 2, "info": 1}

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


def _group(rule: dict) -> str:
    return rule.get("group", rule["id"])


def _fmt(value) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.0f}"
    return "" if value is None else str(value)


def _title(rule: dict, part_label: Optional[str], value=None, **extra) -> str:
    """The plain-language line a reader sees (REQ-GHA-027 clause 5)."""
    template = rule.get("title") or rule.get("description", rule["id"])
    fields = {"part": part_label or "ColdVault", "value": _fmt(value)}
    fields.update({k: _fmt(v) for k, v in extra.items()})
    try:
        return template.format(**fields)
    except (KeyError, IndexError, ValueError):
        return template


def _candidate(rule: dict, node_id: Optional[str], part_label: Optional[str], message: str,
               metric_name: Optional[str] = None, value=None, threshold=None,
               severity: Optional[str] = None, **extra) -> Alert:
    kind = rule.get("kind", "alarm")
    severity = severity or rule.get("severity", "warning")
    if kind in ("example", "observation") and severity == "critical":
        severity = "warning"  # REQ-GHA-028 clause 4: examples are at most a warning
    return Alert(
        rule_id=rule["id"],
        kind=kind,
        severity=severity,
        message=message,
        triggered_at=datetime.now(timezone.utc).isoformat(),
        node_id=node_id,
        metric_name=metric_name,
        metric_value=float(value) if isinstance(value, (int, float)) else None,
        threshold=float(threshold) if threshold is not None else None,
        group=_group(rule),
        title=_title(rule, part_label, value, **extra),
        part_label=part_label,
    )


def _check_node_rule(rule: dict, node: Node,
                     label: Optional[str] = None) -> tuple[bool, Optional[Alert]]:
    """Evaluate a node-scoped rule against one node. Returns (checked, alert or None)."""
    label = label or node.label
    cond = rule.get("condition", {})
    metric_name = cond.get("metric")
    if not metric_name:
        return False, None

    # Filter by node type if specified
    allowed_types = rule.get("node_types")
    if allowed_types and node.type not in allowed_types:
        return False, None
    if node.type in (rule.get("exclude_node_types") or ()):
        return False, None

    # Get value: special case for "status" (check node.status), otherwise node.metrics
    if metric_name == "status":
        value = node.status
        op_fn = _OPS.get(cond.get("operator", "=="))
        if op_fn and op_fn(value, cond.get("value")):
            return True, _candidate(
                rule, node.id, label,
                f"{rule.get('description', rule['id'])}: {label} status={value}",
                metric_name="status")
        return True, None

    # Numeric metric check
    value = node.metrics.get(metric_name)
    threshold = cond.get("threshold")
    op_fn = _OPS.get(cond.get("operator", ">"))
    if value is None or threshold is None or not op_fn:
        return False, None
    try:
        if op_fn(float(value), float(threshold)):
            return True, _candidate(
                rule, node.id, label,
                f"{rule.get('description', rule['id'])}: {label} {metric_name}={value}",
                metric_name=metric_name, value=float(value), threshold=threshold)
    except (ValueError, TypeError):
        return False, None
    return True, None


def _metric_part(source_data: dict, metric_name: str) -> Optional[str]:
    return (source_data.get("parts") or {}).get(metric_name) or source_data.get("part")


def _check_global_rule(rule: dict, snapshot: dict,
                       labels: dict) -> tuple[Optional[tuple], Optional[Alert]]:
    """Evaluate a global-scoped rule against collector data.

    Returns (checked key or None, alert or None). A rule is checked only when its
    source has a value and the source or the rule names the part it belongs to
    (REQ-GHA-027 clauses 3, 6)."""
    cond = rule.get("condition", {})
    source = cond.get("source")
    metric_name = cond.get("metric")
    if not source or not metric_name:
        return None, None

    source_data = snapshot.get(source) or {}
    value = source_data.get(metric_name)
    # The part comes from the source (collectors read per part) or from the rule itself
    part = _metric_part(source_data, metric_name) or rule.get("part")
    threshold = cond.get("threshold")
    op_fn = _OPS.get(cond.get("operator", ">"))
    if value is None or part is None or threshold is None or not op_fn:
        return None, None
    key = (_group(rule), part)
    try:
        fires = op_fn(float(value), float(threshold))
    except (ValueError, TypeError):
        return None, None
    if not fires:
        return key, None
    # REQ-004: the technical message keeps the rule description plus metric=value
    # for webhooks/SIEM; the reader sees the plain title.
    return key, _candidate(
        rule, part, labels.get(part),
        f"{rule.get('description', rule['id'])}: {metric_name}={value}",
        metric_name=metric_name, value=float(value), threshold=threshold)


def _check_anomaly_rule(rule: dict, snapshot: dict,
                        labels: dict) -> tuple[set, list[Alert]]:
    """One alarm per anomaly, in the same group and part as the threshold rules on
    that metric, so one event is one alarm (REQ-GHA-027 clause 2)."""
    data = snapshot.get("anomaly") or {}
    if not data.get("read"):
        return set(), []
    groups = rule.get("groups") or {}
    parts = data.get("parts") or {}
    checked = {(groups.get(m, _group(rule)), p) for m, p in parts.items() if p}
    alerts = []
    for a in data.get("anomalies") or []:
        metric = a.get("metric")
        part = parts.get(metric)
        if not part:
            continue
        alert = _candidate(
            rule, part, labels.get(part),
            f"{rule.get('description', rule['id'])}: {metric}={a.get('value')} "
            f"(baseline {a.get('baseline_mean')}, z={a.get('z_score')})",
            metric_name=metric, value=a.get("value"), severity=a.get("severity"),
            what=_anomaly_name(metric), normal=a.get("baseline_mean"))
        alert.group = groups.get(metric, _group(rule))
        try:
            from src.security.anomaly_detector import classify_anomalies
            alert.anomaly_classification = classify_anomalies([a])
        except Exception as e:
            logger.warning(f"REQ-004: classify_anomalies failed for rule {rule.get('id')!r}: {e}")
        alerts.append(alert)
    return checked, alerts


def _anomaly_name(metric: str) -> str:
    try:
        from src.security.anomaly_detector import METRIC_INFO
        return METRIC_INFO.get(metric, {}).get("name", metric)
    except Exception:
        return metric


def _apply(candidates: list[Alert], checked: set, now: float) -> tuple[list, list]:
    """Merge this round's alarms into the active set. Returns (new, resolved)."""
    now_iso = datetime.fromtimestamp(now, timezone.utc).isoformat()
    by_key: dict[tuple, list[Alert]] = collections.defaultdict(list)
    for c in candidates:
        by_key[(c.group, c.node_id)].append(c)
    new, resolved = [], []
    for key, items in by_key.items():
        # The higher severity wins; at equal severity a trusted alarm wins over an example
        top = max(items, key=lambda a: (_SEVERITY_RANK.get(a.severity, 0), a.kind == "alarm"))
        reasons = [a.message for a in items]
        current = _active.get(key)
        if current is None:
            top.first_seen = top.last_seen = top.triggered_at = now_iso
            top.reasons = reasons
            _active[key] = top
            new.append(top)
            continue
        for field in ("rule_id", "kind", "severity", "message", "title", "part_label", "metric_name",
                      "metric_value", "threshold", "anomaly_classification", "evidence"):
            setattr(current, field, getattr(top, field))
        if top.explanation:  # a review that wrote none keeps the earlier one (REQ-GHA-031)
            current.explanation = top.explanation
        current.last_seen = now_iso
        current.reasons = reasons
    for key in list(_active):
        if key in checked and key not in by_key:
            gone = _active.pop(key)
            gone.ended_at = now_iso
            _resolved.appendleft(gone)
            resolved.append(gone)
    cutoff = now - _RESOLVED_KEEP_S
    while _resolved and datetime.fromisoformat(_resolved[-1].ended_at).timestamp() < cutoff:
        _resolved.pop()
    return new, resolved


def _rules(rules_path: Optional[str]) -> list[dict]:
    """REQ-GHA-028: the alarms the landscape files define; the general rules file only
    when no landscape file defines any (or when a path is given explicitly)."""
    if rules_path is None:
        from src.collectors import alarm_sources
        declared = alarm_sources.alarms()
        if declared is not None:
            return declared
        from src.config.settings import RULES_CONFIG_PATH
        rules_path = RULES_CONFIG_PATH
    return load_rules(rules_path)


def evaluate_rules(nodes: list, snapshot: dict,
                   rules_path: str = None, labels: Optional[dict] = None) -> list[Alert]:
    """Evaluate all rules against current state. Returns the active alarms.

    Only conditions this call could check can start, update or end an alarm, so a
    call with partial data (for example ingest) leaves the others as they are."""
    rules = _rules(rules_path)
    if not rules:
        return []

    now = time.time()
    # labels: the reader's names for parts, over the node labels (manifest nodes carry their id)
    labels = {**{n.id: n.label for n in nodes}, **(labels or {})}
    candidates: list[Alert] = []
    checked: set = set()

    with _lock:
        # Only the rules in force now are listed (a landscape change replaces the defaults)
        _rule_names.clear()
        for rule in rules:
            _rule_names[rule["id"]] =rule.get("name") or rule.get("description", rule["id"])
            scope = rule.get("scope", "node")
            rule_checked = False
            if rule.get("condition", {}).get("source") == "anomaly" and rule.get("per_anomaly"):
                keys, alerts = _check_anomaly_rule(rule, snapshot, labels)
                checked |= keys
                candidates += alerts
                rule_checked = bool(keys)
            elif scope == "global":
                key, alert = _check_global_rule(rule, snapshot, labels)
                if key:
                    checked.add(key)
                    rule_checked = True
                if alert:
                    candidates.append(alert)
            else:  # node scope
                # REQ-GHA-027 clause 2 / REQ-GHA-034: a provider box whose status comes from a
                # failing model already has that model's alarm; its status rule adds no second one
                model_parts = {k[1] for k in _active if str(k[0]).startswith("model:")}
                for node in nodes:
                    if node.id in model_parts and rule.get("condition", {}).get("metric") == "status":
                        checked.add((_group(rule), node.id))
                        rule_checked = True
                        continue
                    node_checked, alert = _check_node_rule(rule, node, labels.get(node.id))
                    if node_checked:
                        checked.add((_group(rule), node.id))
                        rule_checked = True
                    if alert:
                        candidates.append(alert)
            if rule_checked:
                _rule_checked_at[rule["id"]] = now

        if nodes:
            present = {n.id for n in nodes}
            # A part that is gone from the canvas (for example a replaced VM) has no
            # condition left: its alarms end (findings and AI review alarms follow their own checks).
            checked |= {k for k in _active
                        if k[1] is not None and k[1] not in present
                        and not str(k[0]).startswith(("finding:", "ai:", "model:", "provider:"))}
        new_alerts, resolved = _apply(candidates, checked, now)
        active = list(_active.values())

    if new_alerts:
        logger.info(f"Rule engine: {len(new_alerts)} new alerts "
                    f"({sum(1 for a in new_alerts if a.severity == 'critical')} critical)")

    # ALCOA+ audit trail: log every evaluation cycle
    _audit_log.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "rules_evaluated": len(rules),
        "nodes_checked": len(nodes),
        "alerts_new": len(new_alerts),
        "alerts_active": len(active),
        "alerts_resolved": len(resolved),
        "triggered": [
            {"rule_id": a.rule_id, "node_id": a.node_id,
             "severity": a.severity, "metric_name": a.metric_name,
             "metric_value": a.metric_value, "threshold": a.threshold}
            for a in new_alerts
        ],
    })

    return active


def track_findings(findings: list, nodes: list, labels: Optional[dict] = None) -> None:
    """Drift and leftover findings as alarms with the same lifecycle (REQ-GHA-027).

    findings: [{id, text, source, part, active}]; a finding whose check could not
    run is absent, so its alarm (if any) is left as it is."""
    labels = {**{n.id: n.label for n in nodes}, **(labels or {})}
    candidates, checked = [], set()
    for f in findings:
        rule = {"id": f"finding:{f['id']}", "severity": "warning", "title": f["text"],
                "description": "Finding", "kind": "observation"}
        part = f.get("part")
        checked.add((rule["id"], part))
        if f.get("active", True):
            message = f"Finding: {f['text']}" + (f" (source: {f['source']})" if f.get("source") else "")
            alert = _candidate(rule, part, labels.get(part), message)
            alert.title = f"{labels[part]}: {f['text']}" if part in labels else f["text"]
            candidates.append(alert)
    with _lock:
        _apply(candidates, checked, time.time())


def track_ai_review(problems: list, reviewed_parts: set, labels: Optional[dict] = None) -> None:
    """Problems named by the AI log review as alarms (REQ-GHA-029 clauses 1-2).

    problems: [{id, part, severity, title, evidence}]. An open AI alarm on a reviewed part
    that this review no longer names ends, except a critical one nobody has acknowledged:
    that stays until a signed-in person acknowledges it. An AI alarm never gets milder
    while it is open."""
    labels = labels or {}
    now = time.time()
    with _lock:
        checked = {k for k, a in _active.items()
                   if a.kind == "ai" and k[1] in reviewed_parts
                   and not (a.severity == "critical" and not a.acknowledged)}
        candidates = []
        for p in problems:
            group, part = f"ai:{p['id']}", p["part"]
            current = _active.get((group, part))
            severity = p["severity"]
            if current and _SEVERITY_RANK.get(current.severity, 0) > _SEVERITY_RANK.get(severity, 0):
                severity = current.severity
            rule = {"id": "ai_review", "group": group, "severity": severity, "kind": "ai",
                    "description": "Found by AI review"}
            alert = _candidate(rule, part, labels.get(part), f"Found by AI review: {p['title']}")
            alert.title = f"{labels[part]}: {p['title']}" if part in labels else p["title"]
            alert.evidence = list(p.get("evidence") or [])
            alert.explanation = p.get("explanation")
            candidates.append(alert)
        _apply(candidates, checked, now)


def track_model_failures(failures: list, read: bool, labels: Optional[dict] = None) -> None:
    """A failing AI model of the monitored system as an alarm on its provider's box
    (REQ-GHA-034). failures: [{model, part, severity, title, explanation, evidence}].
    When the figures were read, a model no longer failing ends its alarm; when they
    were not read, nothing changes."""
    labels = labels or {}
    with _lock:
        checked = {k for k in _active if str(k[0]).startswith("model:")} if read else set()
        candidates = []
        for f in failures:
            rule = {"id": "model_failure", "group": f"model:{f['model']}", "severity": f["severity"],
                    "kind": "alarm", "description": "AI model failing"}
            part = f["part"]
            checked.add((rule["group"], part))
            alert = _candidate(rule, part, labels.get(part), f"Model failing: {f['title']}")
            alert.title = f"{labels[part]}: {f['title']}" if part in labels else f["title"]
            alert.explanation = f.get("explanation")
            alert.evidence = list(f.get("evidence") or [])
            candidates.append(alert)
        _apply(candidates, checked, time.time())


def _bind_legacy_provider_keys(part_provider: dict) -> None:
    """Alarms saved before provider names were part of the key (provider:<id>) are bound to
    the provider that owns their part, keeping report, acknowledgement and first seen."""
    for key in [k for k in _active if str(k[0]).startswith("provider:") and str(k[0]).count(":") == 1]:
        name = part_provider.get(key[1])
        if not name:
            continue
        alert = _active.pop(key)
        new_key = (f"provider:{name}:{str(key[0]).split(':', 1)[1]}", key[1])
        alert.group = new_key[0]
        current = _active.get(new_key)
        if current is None:
            _active[new_key] = alert
            continue
        # Both exist: keep one alarm, without losing what the old one carried
        if current.report is None and alert.report is not None:
            current.report = alert.report
        if alert.acknowledged and not current.acknowledged:
            current.acknowledged, current.acknowledged_by, current.acknowledged_at = (
                alert.acknowledged, alert.acknowledged_by, alert.acknowledged_at)
        if alert.first_seen and (not current.first_seen or alert.first_seen < current.first_seen):
            current.first_seen = alert.first_seen


def track_provider_incidents(entries: list, read: set, labels: Optional[dict] = None,
                             part_provider: Optional[dict] = None) -> None:
    """A public system's published incident or maintenance as one alarm on the first part it
    names (REQ-GHA-036 clause 4), keeping every part it names. It ends when its provider,
    read this time, no longer lists it as open; a provider not read (absent from `read`)
    leaves its own alarms as they are, whatever the other providers say."""
    labels = labels or {}
    read = set(read or ())
    with _lock:
        _bind_legacy_provider_keys(part_provider or {})
        checked = {k for k in _active if str(k[0]).startswith("provider:")
                   and str(k[0]).split(":", 2)[1] in read}
        candidates = []
        for e in entries:
            rule = {"id": "provider_incident", "group": f"provider:{e['provider']}:{e['id']}", "severity": e["severity"],
                    "kind": "alarm", "description": "Reported by the provider"}
            part = e["part"]
            checked.add((rule["group"], part))
            alert = _candidate(rule, part, labels.get(part), f"Provider reports: {e['title']}")
            alert.title = e["title"]
            alert.explanation = {**(e.get("explanation") or {}), "affected_parts": list(e.get("parts") or [part])}
            alert.evidence = list(e.get("evidence") or [])
            candidates.append(alert)
        _apply(candidates, checked, time.time())


def _kept(a: Alert) -> bool:
    return a.kind == "ai" or a.report is not None


def ai_alarms() -> dict:
    """The AI review's open alarms (what the next review is told about)."""
    with _lock:
        return {"active": [a.to_dict() for a in _active.values() if a.kind == "ai"]}


def saved_alarms() -> dict:
    """What must survive a restart (REQ-GHA-029): every AI alarm, and every alarm of any
    kind that carries an investigation report, open and ended."""
    with _lock:
        return {"active": [a.to_dict() for a in _active.values() if _kept(a)],
                "resolved": [a.to_dict() for a in _resolved if _kept(a)]}


def restore_alarms(saved: dict) -> int:
    """Put saved alarms back after a restart; alarms already present are kept. A restored
    rule alarm is then updated or ended by the next check of its rule, report and all."""
    n = 0
    with _lock:
        for d in saved.get("active") or []:
            a = Alert.from_dict(d)
            if _kept(a) and (a.group, a.node_id) not in _active:
                _active[(a.group, a.node_id)] = a
                n += 1
        known = {(a.group, a.node_id, a.first_seen) for a in _resolved}
        for d in reversed(saved.get("resolved") or []):
            a = Alert.from_dict(d)
            if _kept(a) and a.ended_at and (a.group, a.node_id, a.first_seen) not in known:
                _resolved.appendleft(a)
                n += 1
    return n


def find_alarm(group: str, node_id: Optional[str]) -> Optional[dict]:
    """An open alarm, or an ended one from the last day, by its group and part."""
    with _lock:
        a = _active.get((group, node_id)) or next(
            (r for r in _resolved if r.group == group and r.node_id == node_id), None)
        return a.to_dict() if a else None


def set_report(group: str, node_id: Optional[str], report: dict) -> bool:
    """Save an investigation report with its alarm (REQ-GHA-029 clause 4)."""
    with _lock:
        a = _active.get((group, node_id)) or next(
            (r for r in _resolved if r.group == group and r.node_id == node_id), None)
        if a is None:
            return False
        a.report = report
        return True


def get_alerts() -> list[dict]:
    """Return current active alarms as dicts."""
    with _lock:
        return [a.to_dict() for a in _active.values()]


def get_resolved() -> list[dict]:
    """Alarms that ended within the last day, newest first."""
    with _lock:
        return [a.to_dict() for a in _resolved]


def get_rule_status() -> list[dict]:
    """Each rule and whether it had data recently; unchecked rules raise no alarm."""
    now = time.time()
    with _lock:
        return [{"id": rid, "name": name,
                 "checked": now - _rule_checked_at.get(rid, 0) < _NOT_CHECKED_AFTER_S}
                for rid, name in _rule_names.items()]


def acknowledge_alert(rule_id: str, node_id: Optional[str], user: str) -> bool:
    """Acknowledge an alert. Returns True if found and acknowledged."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with _lock:
        for alert in _active.values():
            if (rule_id in (alert.rule_id, alert.group) and alert.node_id == node_id
                    and not alert.acknowledged):
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
