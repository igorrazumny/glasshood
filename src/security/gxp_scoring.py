# File: src/security/gxp_scoring.py
# Purpose: GxP-aware severity scoring for CVE findings

"""
GxP impact scoring: vulnerabilities on GxP-critical systems are weighted higher.
A CVSS 7.0 on a system carrying batch records is more critical than a 9.0 on a dev server.

Annex 11 Section 10.2 requires security of electronic interfaces between validated systems.
This module ensures CVE severity reflects pharma operational impact, not just technical severity.
"""


def score_severity(cvss_score: float, gxp_critical: bool) -> str:
    """Derive effective severity from CVSS score and GxP criticality.

    GxP-critical components get elevated severity:
    - CVSS >= 9.0 on GxP → critical (vs high on non-GxP)
    - CVSS >= 7.0 on GxP → high (vs medium on non-GxP at 7.0-7.9)
    - CVSS >= 4.0 on GxP → medium (vs low on non-GxP at 4.0-6.9)

    Non-GxP uses standard CVSS severity bands.
    """
    if gxp_critical:
        if cvss_score >= 9.0:
            return "critical"
        if cvss_score >= 7.0:
            return "high"
        if cvss_score >= 4.0:
            return "medium"
        return "low"
    else:
        if cvss_score >= 9.0:
            return "high"
        if cvss_score >= 7.0:
            return "medium"
        if cvss_score >= 4.0:
            return "low"
        return "low"
