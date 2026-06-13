# File: src/models/finding.py
# Purpose: SecurityFinding dataclass for CVE scanner results

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SecurityFinding:
    cve_id: str
    severity: str  # critical, high, medium, low
    cvss_score: float
    description: str
    component_id: str
    component_name: str
    node_ids: list[str] = field(default_factory=list)
    gxp_critical: bool = False
    discovered_at: str = ""  # ISO8601
    status: str = "open"  # open, acknowledged, mitigated, accepted
    status_changed_by: Optional[str] = None
    status_changed_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "cve_id": self.cve_id,
            "severity": self.severity,
            "cvss_score": self.cvss_score,
            "description": self.description,
            "component_id": self.component_id,
            "component_name": self.component_name,
            "node_ids": self.node_ids,
            "gxp_critical": self.gxp_critical,
            "discovered_at": self.discovered_at,
            "status": self.status,
            "status_changed_by": self.status_changed_by,
            "status_changed_at": self.status_changed_at,
        }
