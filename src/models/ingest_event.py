# File: src/models/ingest_event.py
# Purpose: Data model for ingested events from remote agents

from dataclasses import dataclass, field
from typing import Optional


VALID_SOURCE_TYPES = {"file", "syslog", "webhook"}
VALID_SEVERITIES = {"debug", "info", "notice", "warning", "error", "critical", "emergency"}


@dataclass
class IngestEvent:
    source_id: str
    message: str
    source_type: str = "file"  # file, syslog, webhook
    severity: str = "info"
    timestamp: str = ""  # ISO8601, filled by processor if empty
    agent_id: str = ""
    tags: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "message": self.message,
            "source_type": self.source_type,
            "severity": self.severity,
            "timestamp": self.timestamp,
            "agent_id": self.agent_id,
            "tags": self.tags,
        }

    @staticmethod
    def from_dict(data: dict) -> "IngestEvent":
        return IngestEvent(
            source_id=data.get("source_id", ""),
            message=data.get("message", ""),
            source_type=data.get("source_type", "file"),
            severity=data.get("severity", "info"),
            timestamp=data.get("timestamp", ""),
            agent_id=data.get("agent_id", ""),
            tags=data.get("tags", {}),
        )
