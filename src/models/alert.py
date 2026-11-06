# File: src/models/alert.py
# Purpose: Alert dataclass for Layer 1 rule engine findings

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Alert:
    rule_id: str
    severity: str  # critical, warning, info
    message: str
    triggered_at: str  # ISO8601
    node_id: Optional[str] = None
    metric_name: Optional[str] = None
    metric_value: Optional[float] = None
    threshold: Optional[float] = None
    acknowledged: bool = False
    acknowledged_at: Optional[str] = None
    acknowledged_by: Optional[str] = None
    # REQ-004: per-alert snapshot of the anomaly classification at creation
    # time (only populated for source='anomaly' rules). The modal renders
    # this — never a global topology field — so each alert shows the
    # classification recorded when IT triggered, not a moving target.
    anomaly_classification: Optional[dict] = None
    # REQ-GHA-027: one alarm per (group, part); a plain title for the reader, the
    # technical lines behind it, and when it was first seen, last seen and ended.
    group: Optional[str] = None
    title: Optional[str] = None
    part_label: Optional[str] = None
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None
    ended_at: Optional[str] = None
    reasons: list = field(default_factory=list)
    # REQ-GHA-028: "alarm" (trusted), "example" or "observation" (shown on the demo,
    # marked, at most a warning)
    kind: str = "alarm"

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "message": self.message,
            "triggered_at": self.triggered_at,
            "node_id": self.node_id,
            "metric_name": self.metric_name,
            "metric_value": self.metric_value,
            "threshold": self.threshold,
            "acknowledged": self.acknowledged,
            "acknowledged_at": self.acknowledged_at,
            "acknowledged_by": self.acknowledged_by,
            "anomaly_classification": self.anomaly_classification,
            "group": self.group,
            "title": self.title or self.message,
            "part_label": self.part_label,
            "first_seen": self.first_seen or self.triggered_at,
            "last_seen": self.last_seen or self.triggered_at,
            "ended_at": self.ended_at,
            "reasons": list(self.reasons),
            "kind": self.kind,
        }
