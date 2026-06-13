# File: tests/test_topology_assembly.py
# Purpose: Tests for topology assembly (discovery + YAML + enrichment)

from unittest.mock import patch, MagicMock
import pytest

from src.models.topology import Node, Edge
from src.api.routes.topology import walk_children_connects_to, inherit_parent_status


def _mock_collectors():
    """Return patch context managers for all collectors."""
    health = {"status": "healthy", "ram_percent": 62.0, "uptime_seconds": 86400,
              "version": "v2026.03.03"}
    metrics_data = {
        "components": {
            "faiss_rag": {"status": "healthy", "active_stores": 3,
                          "total_vectors": 1250},
            "cloud_sql": {"status": "healthy", "pool_size": 10,
                          "pool_checked_out": 2},
            "llm_providers": {
                "gemini": {"status": "healthy"},
                "claude": {"status": "healthy"},
                "openai": {"status": "healthy"},
                "grok": {"status": "healthy"},
            },
        },
        "system": {"ram_used_percent": 62.0, "disk_used_percent": 45.0},
        "security": {"tls": True},
        "user_stats": {"active": 5},
        "uptime_seconds": 86400,
        "version": "v2026.03.03",
    }
    monitoring = {"lb_latency_ms": 15.0, "lb_request_count_1h": 4200,
                  "vm_cpu_percent": 35.0}
    logging_stats = {"error_count_15m": 0, "recent_errors": []}

    return {
        "src.collectors.coldvault.get_health": patch(
            "src.collectors.coldvault.get_health", return_value=health),
        "src.collectors.coldvault.get_metrics": patch(
            "src.collectors.coldvault.get_metrics", return_value=metrics_data),
        "src.collectors.coldvault.is_stale": patch(
            "src.collectors.coldvault.is_stale", return_value=False),
        "src.collectors.gcp_monitoring.get_stats": patch(
            "src.collectors.gcp_monitoring.get_stats", return_value=monitoring),
        "src.collectors.gcp_logging.get_stats": patch(
            "src.collectors.gcp_logging.get_stats", return_value=logging_stats),
    }


class TestEnrichNodes:
    def test_enriches_vm_node(self):
        from src.api.routes.topology import _enrich_nodes
        nodes = [Node(id="vm-test", label="test", type="vm", status="healthy",
                      source="discovered", metrics={})]
        patches = _mock_collectors()
        with patches["src.collectors.coldvault.get_health"], \
             patches["src.collectors.coldvault.get_metrics"], \
             patches["src.collectors.coldvault.is_stale"], \
             patches["src.collectors.gcp_monitoring.get_stats"], \
             patches["src.collectors.gcp_logging.get_stats"]:
            _enrich_nodes(nodes, [])
        assert nodes[0].metrics["ram_percent"] == 62.0
        assert nodes[0].metrics["cpu_percent"] == 35.0
        assert nodes[0].last_checked is not None

    def test_enriches_gpu_node(self):
        from src.api.routes.topology import _enrich_nodes
        nodes = [Node(id="gpu_h100_spot", label="H100", type="gpu",
                      status="auto", source="yaml", metrics={"health_url": ""})]
        patches = _mock_collectors()
        with patches["src.collectors.coldvault.get_health"], \
             patches["src.collectors.coldvault.get_metrics"], \
             patches["src.collectors.coldvault.is_stale"], \
             patches["src.collectors.gcp_monitoring.get_stats"], \
             patches["src.collectors.gcp_logging.get_stats"]:
            _enrich_nodes(nodes, [])
        assert nodes[0].status == "offline"  # empty health_url = not deployed

    def test_enriches_lb_forwarding_rule(self):
        from src.api.routes.topology import _enrich_nodes
        nodes = [Node(id="fr-test-rule", label="LB: test-rule", type="lb",
                      status="healthy", source="discovered", metrics={})]
        patches = _mock_collectors()
        with patches["src.collectors.coldvault.get_health"], \
             patches["src.collectors.coldvault.get_metrics"], \
             patches["src.collectors.coldvault.is_stale"], \
             patches["src.collectors.gcp_monitoring.get_stats"], \
             patches["src.collectors.gcp_logging.get_stats"]:
            _enrich_nodes(nodes, [])
        assert nodes[0].status == "healthy"

    def test_stale_marks_nodes(self):
        from src.api.routes.topology import _enrich_nodes
        nodes = [Node(id="vm-test", label="test", type="vm", status="healthy",
                      source="discovered", metrics={})]
        patches = _mock_collectors()
        stale_patch = patch("src.collectors.coldvault.is_stale", return_value=True)
        with patches["src.collectors.coldvault.get_health"], \
             patches["src.collectors.coldvault.get_metrics"], \
             stale_patch, \
             patches["src.collectors.gcp_monitoring.get_stats"], \
             patches["src.collectors.gcp_logging.get_stats"]:
            _enrich_nodes(nodes, [])
        assert nodes[0].status == "stale"


class TestBuildTopology:
    @patch("src.api.routes.topology.load_overrides",
           return_value={"nodes": [{"id": "nginx", "label": "nginx",
                                    "type": "nginx", "status": "auto"}],
                         "edges": []})
    @patch("src.api.routes.topology.get_cached_graph",
           return_value={"nodes": [
               Node(id="vm-example-mig-abc", label="VM: abc", type="vm",
                    status="healthy", source="discovered")],
               "edges": []})
    @patch("src.api.routes.topology.manifest_metrics.get_all_statuses",
           return_value={"vm-example-mig-abc": {"_parent": "mig-platform",
                         "status": "healthy", "metrics": {}}})
    def test_merges_and_enriches(self, mock_statuses, mock_graph, mock_overrides):
        from src.api.routes.topology import _build_topology
        patches = _mock_collectors()
        with patches["src.collectors.coldvault.get_health"], \
             patches["src.collectors.coldvault.get_metrics"], \
             patches["src.collectors.coldvault.is_stale"], \
             patches["src.collectors.gcp_monitoring.get_stats"], \
             patches["src.collectors.gcp_logging.get_stats"]:
            result = _build_topology()
        nodes = result["nodes"]
        ids = {n["id"] for n in nodes}
        # MIG-discovered VMs survive filter (have _parent in manifest_metrics)
        assert "vm-example-mig-abc" in ids
        # Org-discovery VMs without _parent would be filtered out
        assert result["overall_status"] in ("healthy", "unknown", "degraded")


class TestWalkChildrenConnectsTo:
    """REQ-702: walk_children_connects_to collects IDs + creates edges."""

    def test_flat_children_with_connects_to(self):
        """Single-level children with connects_to create edges."""
        children = [
            {"id": "vm-abc-api", "connects_to": ["@providers", "@gpu"]},
        ]
        child_ids = set()
        edges = []
        walk_children_connects_to(children, child_ids, edges)
        assert "vm-abc-api" in child_ids
        assert len(edges) == 2
        assert edges[0].source == "vm-abc-api"
        assert edges[0].target == "@providers"
        assert edges[1].target == "@gpu"

    def test_nested_children_with_connects_to(self):
        """Nested children (VM → Docker → App) create edges from innermost."""
        children = [
            {
                "id": "vm-abc-docker",
                "children": [
                    {"id": "vm-abc-api", "connects_to": ["@providers"]},
                ],
            },
        ]
        child_ids = set()
        edges = []
        walk_children_connects_to(children, child_ids, edges)
        assert "vm-abc-docker" in child_ids
        assert "vm-abc-api" in child_ids
        assert len(edges) == 1
        assert edges[0].source == "vm-abc-api"
        assert edges[0].target == "@providers"

    def test_multiple_vms_create_multiple_edges(self):
        """3 VMs with connects_to = 3 edges (50 VMs = 50 edges)."""
        children = [
            {"id": f"vm-{name}-api", "connects_to": ["@providers"]}
            for name in ["aaa", "bbb", "ccc"]
        ]
        child_ids = set()
        edges = []
        walk_children_connects_to(children, child_ids, edges)
        assert len(child_ids) == 3
        assert len(edges) == 3
        sources = {e.source for e in edges}
        assert sources == {"vm-aaa-api", "vm-bbb-api", "vm-ccc-api"}

    def test_no_connects_to_no_edges(self):
        """Children without connects_to don't create edges."""
        children = [
            {"id": "vm-abc-docker", "type": "container"},
        ]
        child_ids = set()
        edges = []
        walk_children_connects_to(children, child_ids, edges)
        assert "vm-abc-docker" in child_ids
        assert len(edges) == 0

    def test_none_children_is_safe(self):
        """None children doesn't crash."""
        child_ids = set()
        edges = []
        walk_children_connects_to(None, child_ids, edges)
        assert len(child_ids) == 0
        assert len(edges) == 0

    def test_inherit_parent_status(self):
        """Children with no status inherit parent VM's status."""
        children = [
            {
                "id": "vm-abc-docker",
                "children": [
                    {"id": "vm-abc-api", "type": "application"},
                ],
            },
        ]
        inherit_parent_status(children, "healthy")
        assert children[0]["status"] == "healthy"
        assert children[0]["children"][0]["status"] == "healthy"

    def test_inherit_parent_status_preserves_explicit(self):
        """Children with explicit non-unknown status are not overwritten."""
        children = [
            {"id": "vm-abc-docker", "status": "error"},
            {"id": "vm-abc-api", "status": "unknown"},  # should be overwritten
        ]
        inherit_parent_status(children, "healthy")
        assert children[0]["status"] == "error"      # preserved
        assert children[1]["status"] == "healthy"    # overwritten from unknown

    def test_scalar_connects_to_ignored(self):
        """YAML scalar string connects_to: "@providers" must not iterate chars."""
        children = [
            {"id": "vm-abc-api", "connects_to": "@providers"},  # scalar, not list
        ]
        child_ids = set()
        edges = []
        walk_children_connects_to(children, child_ids, edges)
        assert "vm-abc-api" in child_ids
        assert len(edges) == 0  # No garbage edges from char iteration

    def test_child_ids_in_allowed_set(self):
        """Child IDs added to set can be used for edge filtering."""
        children = [
            {
                "id": "vm-abc-docker",
                "children": [
                    {"id": "vm-abc-api", "connects_to": ["@providers"]},
                ],
            },
        ]
        child_ids = set()
        edges = []
        walk_children_connects_to(children, child_ids, edges)
        # Simulate the defense-in-depth filter
        allowed_ids = {"pl-mig", "vm-abc"} | child_ids
        filtered = [e for e in edges
                    if (e.source in allowed_ids or e.source.startswith("@"))
                    and (e.target in allowed_ids or e.target.startswith("@"))]
        # Edge from vm-abc-api → @providers survives filter
        assert len(filtered) == 1
