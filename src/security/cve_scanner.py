# File: src/security/cve_scanner.py
# Purpose: CVE scanner — queries NVD API for known vulnerabilities on declared components

import collections
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
import yaml

from src.models.finding import SecurityFinding

logger = logging.getLogger(__name__)

NVD_API_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"
NVD_QUERY_DELAY = 6  # seconds between queries (respects 5 req/30s without API key)

_findings: list[SecurityFinding] = []
_lock = threading.Lock()
_last_poll: float = 0

# ALCOA+ audit trail for security scans
_audit_log: collections.deque = collections.deque(maxlen=200)


def _load_components(path: str) -> tuple[dict, list[dict]]:
    """Load scan config and component declarations from YAML."""
    p = Path(path)
    if not p.exists():
        logger.warning(f"Security scan config not found: {path}")
        return {}, []
    try:
        with open(p) as f:
            data = yaml.safe_load(f) or {}
        scan_config = data.get("scan", {})
        components = data.get("components", [])
        logger.info(f"Loaded {len(components)} components from {path}")
        return scan_config, components
    except Exception as e:
        logger.error(f"Failed to load security scan config: {e}")
        return {}, []


def _query_nvd(cpe: str, api_key: str = "") -> list[dict]:
    """Query NVD API 2.0 for CVEs matching a CPE string."""
    headers = {}
    if api_key:
        headers["apiKey"] = api_key
    try:
        resp = requests.get(
            NVD_API_URL,
            params={"cpeName": cpe, "resultsPerPage": 20},
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("vulnerabilities", [])
    except requests.RequestException as e:
        logger.warning(f"NVD query failed for {cpe}: {e}")
        return []


def _parse_cvss(cve_item: dict) -> tuple[float, str]:
    """Extract CVSS score and severity from NVD CVE item."""
    metrics = cve_item.get("cve", {}).get("metrics", {})
    # Prefer CVSS v3.1, fall back to v3.0, then v2
    for key in ("cvssMetricV31", "cvssMetricV30"):
        entries = metrics.get(key, [])
        if entries:
            cvss = entries[0].get("cvssData", {})
            score = cvss.get("baseScore", 0.0)
            severity = cvss.get("baseSeverity", "MEDIUM").lower()
            return score, severity
    # CVSS v2 fallback
    v2 = metrics.get("cvssMetricV2", [])
    if v2:
        score = v2[0].get("cvssData", {}).get("baseScore", 0.0)
        if score >= 7.0:
            return score, "high"
        if score >= 4.0:
            return score, "medium"
        return score, "low"
    return 0.0, "low"


def _scan_component(component: dict, api_key: str = "") -> list[SecurityFinding]:
    """Scan a single component against NVD. Returns findings."""
    cpe = component.get("cpe", "")
    if not cpe:
        return []

    vulns = _query_nvd(cpe, api_key)
    findings = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for vuln in vulns:
        cve_data = vuln.get("cve", {})
        cve_id = cve_data.get("id", "")
        if not cve_id:
            continue

        score, _raw_severity = _parse_cvss(vuln)
        from src.security.gxp_scoring import score_severity
        gxp = component.get("gxp_critical", False)
        severity = score_severity(score, gxp)
        descriptions = cve_data.get("descriptions", [])
        desc = next((d["value"] for d in descriptions if d.get("lang") == "en"), "")

        findings.append(SecurityFinding(
            cve_id=cve_id,
            severity=severity,
            cvss_score=score,
            description=desc[:300],  # truncate long descriptions
            component_id=component["id"],
            component_name=component.get("name", component["id"]),
            node_ids=component.get("node_ids", []),
            gxp_critical=component.get("gxp_critical", False),
            discovered_at=now_iso,
        ))
    return findings


def poll_once():
    """Scan all declared components against NVD."""
    global _last_poll
    from src.config.settings import SECURITY_SCAN_CONFIG_PATH, NVD_API_KEY

    scan_config, components = _load_components(SECURITY_SCAN_CONFIG_PATH)
    if not components:
        return

    if not scan_config.get("enabled", True):
        logger.info("Security scanning disabled in config")
        return

    api_key = NVD_API_KEY or scan_config.get("nvd_api_key", "")
    all_findings = []

    for i, component in enumerate(components):
        if i > 0:
            time.sleep(NVD_QUERY_DELAY)
        try:
            findings = _scan_component(component, api_key)
            all_findings.extend(findings)
            logger.info(f"CVE scan {component['id']}: {len(findings)} findings")
        except Exception as e:
            logger.warning(f"CVE scan failed for {component.get('id', '?')}: {e}")

    with _lock:
        _findings[:] = all_findings
        _last_poll = time.time()

    logger.info(f"CVE scan complete: {len(all_findings)} total findings "
                f"across {len(components)} components")

    _audit_log.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": "scan",
        "components_scanned": len(components),
        "findings_total": len(all_findings),
        "findings_critical": sum(1 for f in all_findings if f.severity == "critical"),
        "findings_high": sum(1 for f in all_findings if f.severity == "high"),
    })


def poll_loop():
    """Background polling loop (runs in thread)."""
    from src.config.settings import SECURITY_SCAN_CONFIG_PATH
    scan_config, _ = _load_components(SECURITY_SCAN_CONFIG_PATH)
    interval = scan_config.get("interval_hours", 6) * 3600

    stop = threading.Event()
    poll_once()
    while not stop.wait(interval):
        poll_once()


def get_findings() -> list[dict]:
    """Return cached CVE findings as dicts."""
    with _lock:
        return [f.to_dict() for f in _findings]


def update_finding_status(cve_id: str, status: str, user: str) -> bool:
    """Update remediation status of a CVE finding. ALCOA+ audit-trailed."""
    valid = {"acknowledged", "mitigated", "accepted"}
    if status not in valid:
        return False
    now_iso = datetime.now(timezone.utc).isoformat()
    with _lock:
        for finding in _findings:
            if finding.cve_id == cve_id:
                finding.status = status
                finding.status_changed_by = user
                finding.status_changed_at = now_iso
                logger.info(f"CVE {cve_id} status -> {status} by {user}")
                _audit_log.append({
                    "timestamp": now_iso,
                    "action": "status_change",
                    "cve_id": cve_id,
                    "new_status": status,
                    "changed_by": user,
                })
                return True
    return False


def get_stats() -> dict:
    """Return summary stats for rule engine integration."""
    with _lock:
        total = len(_findings)
        critical_gxp = sum(1 for f in _findings
                           if f.severity == "critical" and f.gxp_critical)
        high_count = sum(1 for f in _findings if f.severity == "high")
        open_count = sum(1 for f in _findings if f.status == "open")
        return {
            "total": total,
            "critical_gxp_count": critical_gxp,
            "high_count": high_count,
            "open_count": open_count,
            "last_scan": _last_poll,
        }


def get_audit_log() -> list[dict]:
    """Return ALCOA+ audit trail entries (most recent first)."""
    return list(reversed(_audit_log))
