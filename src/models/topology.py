# File: src/models/topology.py
# Purpose: Topology data model — nodes, edges, status

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class Node:
    id: str
    label: str
    type: str  # lb, vm, rag, db, llm, gpu, nginx
    status: str = "unknown"  # healthy, degraded, error, disconnected, unknown
    icon: str = ""
    metrics: dict = field(default_factory=dict)
    last_checked: Optional[str] = None
    source: str = "discovered"  # discovered, yaml, collector
    gcp_resource_type: Optional[str] = None  # e.g. compute.googleapis.com/Instance
    project: str = ""  # product name: coldvault, glasshood, platform, etc.
    env: str = ""  # environment: prod, val
    project_id: str = ""  # GCP project ID (e.g. example-legacy-project)
    children: list = None  # Nested child nodes (VM → Container → App)

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "label": self.label,
            "type": self.type,
            "status": self.status,
            "icon": self.icon,
            "metrics": self.metrics,
            "last_checked": self.last_checked,
            "source": self.source,
            "gcp_resource_type": self.gcp_resource_type,
            "project": self.project,
            "env": self.env,
            "project_id": self.project_id,
        }
        if self.children:
            d["children"] = self.children
        return d


@dataclass
class Edge:
    source: str
    target: str
    label: str = ""
    status: str = "unknown"
    latency_ms: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "target": self.target,
            "label": self.label,
            "status": self.status,
            "latency_ms": self.latency_ms,
        }


@dataclass
class Topology:
    nodes: list = field(default_factory=list)
    edges: list = field(default_factory=list)
    overall_status: str = "unknown"
    last_updated: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "overall_status": self.overall_status,
            "last_updated": self.last_updated,
        }

    def update_overall_status(self):
        # Only consider active nodes — skip non-live statuses
        # REQ-GHA-023: "not checked" (an outside service GlassHood cannot check) says nothing
        # about health, so it neither greens nor degrades the overall status.
        # REQ-GHA-034: "idle" (a model provider with no calls this hour) is not a problem either.
        skip = ("disconnected", "planned", "deployed", "offline", "disabled", "not checked", "idle")
        statuses = [n.status for n in self.nodes if n.status not in skip]
        if not statuses:  # nothing checked (or nothing at all) proves nothing
            self.overall_status = "unknown"
        elif any(s == "error" for s in statuses):
            self.overall_status = "error"
        elif any(s == "degraded" for s in statuses):
            self.overall_status = "degraded"
        elif all(s == "healthy" for s in statuses):
            self.overall_status = "healthy"
        else:
            self.overall_status = "degraded"
        self.last_updated = datetime.now(timezone.utc).isoformat()
