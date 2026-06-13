# File: src/compliance/regulatory.py
# Purpose: Regulatory mapping — Annex 11, ALCOA+, 21 CFR Part 11 section definitions

REGULATIONS = {
    "annex_11_10.2": {
        "id": "annex_11_10.2",
        "title": "EU GMP Annex 11 Section 10.2 — Interface Validation",
        "description": "Electronic interfaces must ensure data completeness, accuracy, and security",
        "applies_to": ["rule_alert", "cve_finding", "anomaly", "correlation"],
        "evidence_requirements": ["data_flow_completeness", "interface_security", "error_monitoring"],
    },
    "alcoa_attributable": {
        "id": "alcoa_attributable",
        "title": "ALCOA+ — Attributable",
        "description": "Every action must be traceable to the person or system that performed it",
        "applies_to": ["rule_alert", "cve_finding", "correlation"],
        "evidence_requirements": ["audit_trail", "user_identification"],
    },
    "alcoa_legible": {
        "id": "alcoa_legible",
        "title": "ALCOA+ — Legible",
        "description": "Data must be readable and permanently recorded",
        "applies_to": ["rule_alert", "cve_finding", "anomaly", "correlation"],
        "evidence_requirements": ["structured_format", "timestamp_integrity"],
    },
    "alcoa_contemporaneous": {
        "id": "alcoa_contemporaneous",
        "title": "ALCOA+ — Contemporaneous",
        "description": "Data must be recorded at the time the activity is performed",
        "applies_to": ["rule_alert", "anomaly"],
        "evidence_requirements": ["real_time_recording", "timestamp_integrity"],
    },
    "alcoa_original": {
        "id": "alcoa_original",
        "title": "ALCOA+ — Original",
        "description": "Data must be the original record or a certified true copy",
        "applies_to": ["rule_alert", "cve_finding", "anomaly", "correlation"],
        "evidence_requirements": ["immutable_record", "audit_trail"],
    },
    "alcoa_accurate": {
        "id": "alcoa_accurate",
        "title": "ALCOA+ — Accurate",
        "description": "Data must be correct and reflect the actual observation",
        "applies_to": ["rule_alert", "anomaly"],
        "evidence_requirements": ["data_validation", "calibrated_thresholds"],
    },
    "21cfr_part11_11.10a": {
        "id": "21cfr_part11_11.10a",
        "title": "21 CFR Part 11 Section 11.10(a) — System Validation",
        "description": "Systems must ensure authenticity, integrity, and confidentiality of electronic records",
        "applies_to": ["cve_finding", "anomaly", "correlation"],
        "evidence_requirements": ["system_validation", "security_controls"],
    },
    "21cfr_part11_11.10e": {
        "id": "21cfr_part11_11.10e",
        "title": "21 CFR Part 11 Section 11.10(e) — Audit Trail",
        "description": "Secure audit trails must independently record date/time of operator entries",
        "applies_to": ["rule_alert", "cve_finding"],
        "evidence_requirements": ["audit_trail", "timestamp_integrity"],
    },
}


def get_applicable_regulations(finding_type: str) -> list[dict]:
    """Return regulatory sections applicable to a finding type."""
    result = []
    for reg in REGULATIONS.values():
        if finding_type in reg["applies_to"]:
            result.append({"id": reg["id"], "title": reg["title"]})
    return result


def tag_finding(finding: dict, finding_type: str) -> dict:
    """Add regulatory_refs list to a finding dict. Returns new dict."""
    tagged = dict(finding)
    tagged["regulatory_refs"] = [
        reg["id"] for reg in REGULATIONS.values()
        if finding_type in reg["applies_to"]
    ]
    tagged["finding_type"] = finding_type
    return tagged
