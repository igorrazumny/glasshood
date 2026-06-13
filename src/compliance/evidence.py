# File: src/compliance/evidence.py
# Purpose: Evidence aggregator — collects findings from all monitoring modules

import logging
from datetime import datetime, timezone

from src.compliance.regulatory import tag_finding

logger = logging.getLogger(__name__)


def _filter_by_period(entries: list[dict], period_start: str = None,
                      period_end: str = None) -> list[dict]:
    """Filter audit trail entries by timestamp period."""
    if not period_start and not period_end:
        return entries

    start_dt = datetime.fromisoformat(period_start) if period_start else None
    end_dt = datetime.fromisoformat(period_end) if period_end else None
    filtered = []
    for entry in entries:
        ts = entry.get("timestamp", "")
        if not ts:
            continue
        try:
            entry_dt = datetime.fromisoformat(ts)
            if start_dt and entry_dt < start_dt:
                continue
            if end_dt and entry_dt > end_dt:
                continue
            filtered.append(entry)
        except (ValueError, TypeError):
            continue
    return filtered


def collect_evidence(period_start: str = None, period_end: str = None) -> dict:
    """Aggregate evidence from all monitoring sources.

    Returns structured dict with current_state, audit_trails, and summary.
    """
    from src.rules.engine import get_alerts, get_audit_log as get_rules_audit
    from src.security.cve_scanner import (
        get_findings, get_stats as get_cve_stats,
        get_audit_log as get_cve_audit,
    )
    from src.security.anomaly_detector import (
        get_anomalies, get_stats as get_anomaly_stats,
        get_audit_log as get_anomaly_audit,
    )
    from src.security.correlator import get_audit_log as get_correlator_audit

    now_iso = datetime.now(timezone.utc).isoformat()

    # Collect current state from all modules
    alerts = get_alerts()
    cve_findings = get_findings()
    anomalies = get_anomalies()
    cve_stats = get_cve_stats()
    anomaly_stats = get_anomaly_stats()

    # Tag each item with applicable regulatory sections
    tagged_alerts = [tag_finding(a, "rule_alert") for a in alerts]
    tagged_cve = [tag_finding(f, "cve_finding") for f in cve_findings]
    tagged_anomalies = [tag_finding(a, "anomaly") for a in anomalies]

    # Collect and filter audit trails by period
    rules_audit = _filter_by_period(get_rules_audit(), period_start, period_end)
    cve_audit = _filter_by_period(get_cve_audit(), period_start, period_end)
    anomaly_audit = _filter_by_period(get_anomaly_audit(), period_start, period_end)
    correlator_audit = _filter_by_period(get_correlator_audit(), period_start, period_end)

    # Severity counts across all findings
    all_findings = tagged_alerts + tagged_cve + tagged_anomalies
    severity_counts = {}
    for f in all_findings:
        sev = f.get("severity", "unknown")
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    return {
        "collected_at": now_iso,
        "period_start": period_start,
        "period_end": period_end,
        "current_state": {
            "alerts": tagged_alerts,
            "cve_findings": tagged_cve,
            "anomalies": tagged_anomalies,
        },
        "audit_trails": {
            "rules": rules_audit,
            "security": cve_audit,
            "anomalies": anomaly_audit,
            "correlations": correlator_audit,
        },
        "summary": {
            "total_alerts": len(alerts),
            "total_cve_findings": len(cve_findings),
            "total_anomalies": len(anomalies),
            "cve_stats": cve_stats,
            "anomaly_stats": anomaly_stats,
            "severity_counts": severity_counts,
            "audit_trail_entries": {
                "rules": len(rules_audit),
                "security": len(cve_audit),
                "anomalies": len(anomaly_audit),
                "correlations": len(correlator_audit),
            },
        },
    }
