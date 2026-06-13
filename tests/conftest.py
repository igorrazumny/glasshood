# File: tests/conftest.py
# Purpose: Shared pytest fixtures for GlassHood tests

import pytest
from src.models.topology import Node, Edge


@pytest.fixture
def sample_topology_data():
    """Realistic topology dict as returned by _build_topology()."""
    return {
        "nodes": [
            {"id": "lb", "label": "Load Balancer", "type": "lb", "status": "healthy",
             "metrics": {"latency_ms": 12.5, "request_count_1h": 4200}},
            {"id": "vm-1", "label": "example-vm", "type": "vm", "status": "healthy",
             "metrics": {"cpu_percent": 35.2, "ram_percent": 62.1}},
            {"id": "nginx", "label": "nginx", "type": "nginx", "status": "healthy"},
            {"id": "faiss", "label": "FAISS RAG", "type": "rag", "status": "healthy",
             "metrics": {"vectors": 1250}},
        ],
        "edges": [
            {"source": "lb", "target": "vm-1", "label": "forwards"},
            {"source": "vm-1", "target": "nginx", "label": "contains"},
        ],
        "overall_status": "healthy",
    }


@pytest.fixture
def sample_nodes():
    """List of Node dataclasses for testing."""
    return [
        Node(id="lb-1", label="Load Balancer", type="lb", status="healthy",
             source="discovered", gcp_resource_type="compute.googleapis.com/ForwardingRule"),
        Node(id="vm-1", label="example-vm", type="vm", status="healthy",
             source="discovered", gcp_resource_type="compute.googleapis.com/Instance"),
        Node(id="backend-1", label="Backend Service", type="lb", status="healthy",
             source="discovered", gcp_resource_type="compute.googleapis.com/BackendService"),
    ]


@pytest.fixture
def sample_edges():
    """List of Edge dataclasses for testing."""
    return [
        Edge(source="lb-1", target="backend-1", label="routes_to"),
        Edge(source="backend-1", target="vm-1", label="uses_backend"),
    ]


@pytest.fixture
def sample_yaml_overrides():
    """Sample YAML override content as parsed dict."""
    return {
        "nodes": [
            {"id": "nginx", "label": "nginx", "type": "nginx", "icon": "globe",
             "status": "auto"},
            {"id": "faiss", "label": "FAISS RAG", "type": "rag", "icon": "database",
             "status": "auto"},
            {"id": "llm_router", "label": "LLM Router", "type": "llm", "icon": "brain",
             "status": "auto"},
        ],
        "edges": [
            {"source": "nginx", "target": "{discovered:BackendService}", "label": "proxy"},
        ],
    }


@pytest.fixture
def sample_gcp_assets():
    """Mocked GCP Cloud Asset Inventory responses."""
    return [
        {
            "asset_type": "compute.googleapis.com/ForwardingRule",
            "name": "//compute.googleapis.com/projects/example-monitoring-project/global/forwardingRules/coldvault-lb-rule",
            "resource": {
                "data": {
                    "name": "coldvault-lb-rule",
                    "IPAddress": "34.8.142.111",
                    "target": "projects/example-monitoring-project/global/targetHttpsProxies/coldvault-proxy",
                    "portRange": "443-443",
                    "status": "RUNNING",
                },
            },
        },
        {
            "asset_type": "compute.googleapis.com/BackendService",
            "name": "//compute.googleapis.com/projects/example-monitoring-project/global/backendServices/coldvault-backend",
            "resource": {
                "data": {
                    "name": "coldvault-backend",
                    "backends": [
                        {"group": "projects/example-monitoring-project/zones/us-central1-a/instanceGroups/coldvault-group"}
                    ],
                    "securityPolicy": "projects/example-monitoring-project/global/securityPolicies/coldvault-armor",
                },
            },
        },
        {
            "asset_type": "compute.googleapis.com/Instance",
            "name": "//compute.googleapis.com/projects/example-monitoring-project/zones/us-central1-a/instances/example-vm",
            "resource": {
                "data": {
                    "name": "example-vm",
                    "status": "RUNNING",
                    "machineType": "zones/us-central1-a/machineTypes/n2d-highmem-8",
                    "confidentialInstanceConfig": {"enableConfidentialCompute": True},
                    "zone": "us-central1-a",
                },
            },
        },
        {
            "asset_type": "compute.googleapis.com/SecurityPolicy",
            "name": "//compute.googleapis.com/projects/example-monitoring-project/global/securityPolicies/coldvault-armor",
            "resource": {
                "data": {
                    "name": "coldvault-armor",
                    "type": "CLOUD_ARMOR",
                },
            },
        },
    ]
