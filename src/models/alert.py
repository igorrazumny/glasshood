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
        }
