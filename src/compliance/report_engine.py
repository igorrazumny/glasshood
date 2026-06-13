# File: src/compliance/report_engine.py
# Purpose: Compliance report generator — Annex 11, ALCOA+, 21 CFR Part 11

import collections
import logging
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

from src.compliance.evidence import collect_evidence
from src.compliance.regulatory import REGULATIONS

logger = logging.getLogger(__name__)

_audit_log: collections.deque = collections.deque(maxlen=100)
_lock = threading.Lock()
_report_counter = 0

VALID_REPORT_TYPES = {"annex_11", "alcoa_plus", "21cfr_part11", "full"}

# Mapping from report type to applicable regulation prefixes
_REPORT_TYPE_PREFIXES = {
    "annex_11": ["annex_11"],
    "alcoa_plus": ["alcoa_"],
    "21cfr_part11": ["21cfr_"],
    "full": None,  # None = include all
}


def _load_config(path: str) -> dict:
    """Load compliance config from YAML."""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        with open(p) as f:
            data = yaml.safe_load(f) or {}
        return data.get("compliance", {})
    except Exception as e:
        logger.error(f"Failed to load compliance config: {e}")
        return {}


def _next_report_id() -> str:
    """Generate sequential report ID: GH-RPT-YYYY-MM-DD-NNN."""
    global _report_counter
    with _lock:
        _report_counter += 1
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return f"GH-RPT-{date_str}-{_report_counter:03d}"


def _filter_by_report_type(findings: list[dict], report_type: str) -> list[dict]:
    """Filter findings to those relevant to the report type."""
    prefixes = _REPORT_TYPE_PREFIXES.get(report_type)
    if prefixes is None:  # "full" — include everything
        return findings
    filtered = []
    for f in findings:
        refs = f.get("regulatory_refs", [])
        if any(ref.startswith(p) for ref in refs for p in prefixes):
            filtered.append(f)
    return filtered


def _derive_compliance_status(findings: list[dict]) -> str:
    """Derive overall compliance status from findings."""
    if not findings:
        return "compliant"
    if any(f.get("severity") == "critical" for f in findings):
        return "non_compliant"
    return "findings_present"


def _get_regulatory_coverage(findings: list[dict], report_type: str) -> dict:
    """Compute coverage status per regulatory section."""
    prefixes = _REPORT_TYPE_PREFIXES.get(report_type)
    coverage = {}
    for reg_id, reg in REGULATIONS.items():
        # Skip regulations not relevant to this report type
        if prefixes and not any(reg_id.startswith(p) for p in prefixes):
            continue
        evidence_count = sum(
            1 for f in findings if reg_id in f.get("regulatory_refs", [])
        )
        coverage[reg_id] = {
            "title": reg["title"],
            "status": "findings" if evidence_count > 0 else "covered",
            "evidence_count": evidence_count,
        }
    return coverage


def generate_report(report_type: str, period_start: str = None,
                    period_end: str = None) -> dict:
    """Generate a compliance evidence report.

    Args:
        report_type: annex_11, alcoa_plus, 21cfr_part11, or full
        period_start: ISO8601 start of reporting period (optional)
        period_end: ISO8601 end of reporting period (optional, defaults to now)
    """
    from src.config.settings import COMPLIANCE_CONFIG_PATH
    config = _load_config(COMPLIANCE_CONFIG_PATH)

    now_iso = datetime.now(timezone.utc).isoformat()
    if not period_end:
        period_end = now_iso
    if not period_start:
        hours = config.get("default_period_hours", 24)
        period_start = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    report_id = _next_report_id()

    # Collect evidence from all sources
    evidence = collect_evidence(period_start, period_end)

    # Merge all findings into one list for filtering
    all_findings = (
        evidence["current_state"]["alerts"]
        + evidence["current_state"]["cve_findings"]
        + evidence["current_state"]["anomalies"]
    )

    # Filter to findings relevant to this report type
    filtered = _filter_by_report_type(all_findings, report_type)

    # Severity breakdown
    severity_counts = {}
    for f in filtered:
        sev = f.get("severity", "unknown")
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    # Regulation breakdown
    regulation_counts = {}
    for f in filtered:
        for ref in f.get("regulatory_refs", []):
            regulation_counts[ref] = regulation_counts.get(ref, 0) + 1

    compliance_status = _derive_compliance_status(filtered)
    regulatory_coverage = _get_regulatory_coverage(filtered, report_type)

    report = {
        "report_metadata": {
            "report_id": report_id,
            "report_type": report_type,
            "generated_at": now_iso,
            "period_start": period_start,
            "period_end": period_end,
            "organization": config.get("organization", ""),
            "system_name": config.get("system_name", "GlassHood"),
            "system_version": config.get("system_version", ""),
        },
        "executive_summary": {
            "compliance_status": compliance_status,
            "total_findings": len(filtered),
            "critical_findings": severity_counts.get("critical", 0),
            "findings_by_severity": severity_counts,
            "findings_by_regulation": regulation_counts,
        },
        "findings": filtered,
        "audit_trail_summary": evidence["summary"]["audit_trail_entries"],
        "regulatory_coverage": regulatory_coverage,
    }

    # ALCOA+ audit trail for report generation
    _audit_log.append({
        "timestamp": now_iso,
        "action": "generate_report",
        "report_id": report_id,
        "report_type": report_type,
        "period_start": period_start,
        "period_end": period_end,
        "total_findings": len(filtered),
        "compliance_status": compliance_status,
    })

    logger.info(f"Compliance report generated: {report_id} type={report_type} "
                f"status={compliance_status} findings={len(filtered)}")

    return report


def get_available_report_types() -> list[dict]:
    """Return available report types with descriptions."""
    return [
        {"id": "annex_11", "title": "EU GMP Annex 11 Section 10.2 — Interface Validation"},
        {"id": "alcoa_plus", "title": "ALCOA+ Compliance Report"},
        {"id": "21cfr_part11", "title": "21 CFR Part 11 — Electronic Records"},
        {"id": "full", "title": "Full Compliance Report (All Regulations)"},
    ]


def get_report_audit_log() -> list[dict]:
    """Return ALCOA+ audit trail of report generation events (most recent first)."""
    return list(reversed(_audit_log))
