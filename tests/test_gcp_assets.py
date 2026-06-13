# File: tests/test_gcp_assets.py
# Purpose: Tests for GCP auto-discovery engine

from unittest.mock import patch, MagicMock
import pytest


def _reset_module():
    """Reset module globals between tests."""
    import src.discovery.gcp_assets as mod
    mod._cached_graph = {"nodes": [], "edges": [], "timestamp": None}
    mod._project_permissions = {}  # {project_id: (bool, timestamp)}


class TestHelpers:
    def test_ref_extracts_last_segment(self):
        from src.discovery.gcp_assets import _ref
        assert _ref("projects/p/zones/z/instances/my-vm") == "my-vm"
        assert _ref("") == ""

    def test_short_type(self):
        from src.discovery.gcp_assets import _short_type
        assert _short_type("compute.googleapis.com/Instance") == "Instance"

    def test_node_id(self):
        from src.discovery.gcp_assets import _node_id
        assert _node_id("compute.googleapis.com/Instance", "vm-1") == "vm-vm-1"
        assert _node_id("compute.googleapis.com/BackendService", "bs-1") == "bs-bs-1"

    def test_parse_zone_from_url(self):
        from src.discovery.gcp_assets import _parse_zone
        assert _parse_zone({"zone": "zones/us-central1-a"}) == "us-central1-a"
        assert _parse_zone({"zone": "us-central1-a"}) == "us-central1-a"


class TestMakeNode:
    def test_instance_node(self):
        from src.discovery.gcp_assets import _make_node
        node = _make_node("compute.googleapis.com/Instance", "my-vm", {
            "status": "RUNNING",
            "machineType": "zones/z/machineTypes/n2d-highmem-8",
            "confidentialInstanceConfig": {"enableConfidentialCompute": True},
            "zone": "us-central1-a",
        })
        assert node.id == "vm-my-vm"
        assert node.type == "vm"
        assert node.status == "healthy"
        assert node.metrics["confidential"] is True
        assert node.source == "discovered"

    def test_forwarding_rule_node(self):
        from src.discovery.gcp_assets import _make_node
        node = _make_node("compute.googleapis.com/ForwardingRule", "lb-rule", {
            "IPAddress": "34.8.142.111",
            "portRange": "443-443",
        })
        assert node.id == "fr-lb-rule"
        assert node.label == "LB: lb-rule"
        assert node.metrics["ip"] == "34.8.142.111"

    def test_terminated_instance(self):
        from src.discovery.gcp_assets import _make_node
        node = _make_node("compute.googleapis.com/Instance", "dead-vm",
                          {"status": "TERMINATED"})
        assert node.status == "error"


class TestIAMPreflight:
    def setup_method(self):
        _reset_module()

    def test_preflight_cached_per_project(self):
        """Per-project permission caching — different projects can have different results."""
        import time
        import src.discovery.gcp_assets as mod
        from src.discovery.gcp_assets import _check_permissions
        now = time.time()
        mod._project_permissions = {
            "allowed-project": (True, now),
            "denied-project": (False, now),
        }
        assert _check_permissions("allowed-project") is True
        assert _check_permissions("denied-project") is False

    def test_preflight_isolation(self):
        """Failing one project does NOT disable discovery for others."""
        import time
        import src.discovery.gcp_assets as mod
        from src.discovery.gcp_assets import _check_permissions
        mod._project_permissions = {"project-a": (False, time.time())}
        assert _check_permissions("project-a") is False
        # project-b not cached yet — would trigger API call (not cached as False)
        assert "project-b" not in mod._project_permissions

    def test_preflight_failure_ttl_expires(self):
        """Failed permission checks expire after TTL — retries the API call."""
        import src.discovery.gcp_assets as mod
        from src.discovery.gcp_assets import _check_permissions
        # Set a failure from 10 minutes ago (> 5 min TTL)
        mod._project_permissions = {"stale-project": (False, 0)}
        # Mock the lazy google.cloud.asset_v1 import inside _check_permissions
        mock_client = MagicMock()
        mock_client.list_assets.return_value = iter([])
        mock_module = MagicMock()
        mock_module.AssetServiceClient.return_value = mock_client
        mock_module.types.ContentType.RESOURCE = 1
        with patch.dict("sys.modules", {"google.cloud.asset_v1": mock_module,
                                         "google.cloud": MagicMock(asset_v1=mock_module)}):
            result = _check_permissions("stale-project")
        assert result is True
        assert mod._project_permissions["stale-project"][0] is True
        mock_client.list_assets.assert_called_once()

    def test_preflight_success_ttl_not_expired(self):
        """Successful permission checks stay cached within TTL."""
        import time
        import src.discovery.gcp_assets as mod
        from src.discovery.gcp_assets import _check_permissions
        # Set a success from just now (within 1h TTL)
        mod._project_permissions = {"fresh-project": (True, time.time())}
        # Should return cached value without API call
        result = _check_permissions("fresh-project")
        assert result is True


class TestBuildGraph:
    def setup_method(self):
        _reset_module()

    @patch("src.discovery.gcp_assets._resolve_ig_members", return_value=["example-vm"])
    @patch("src.discovery.gcp_assets._check_permissions", return_value=True)
    @patch("src.discovery.gcp_assets._list_assets")
    def test_full_graph(self, mock_list, mock_perm, mock_ig):
        from src.discovery.gcp_assets import build_graph
        mock_list.return_value = [
            {"asset_type": "compute.googleapis.com/ForwardingRule",
             "name": "//compute.googleapis.com/projects/p/global/forwardingRules/lb-rule",
             "data": {"name": "lb-rule", "IPAddress": "34.8.142.111",
                      "target": "projects/p/global/targetHttpsProxies/proxy-1",
                      "portRange": "443-443"}},
            {"asset_type": "compute.googleapis.com/TargetHttpsProxy",
             "name": "//compute.googleapis.com/projects/p/global/targetHttpsProxies/proxy-1",
             "data": {"name": "proxy-1",
                      "urlMap": "projects/p/global/urlMaps/map-1"}},
            {"asset_type": "compute.googleapis.com/UrlMap",
             "name": "//compute.googleapis.com/projects/p/global/urlMaps/map-1",
             "data": {"name": "map-1",
                      "defaultService": "projects/p/global/backendServices/backend-1"}},
            {"asset_type": "compute.googleapis.com/BackendService",
             "name": "//compute.googleapis.com/projects/p/global/backendServices/backend-1",
             "data": {"name": "backend-1",
                      "backends": [{"group": "projects/p/zones/us-central1-a/instanceGroups/ig-1"}],
                      "securityPolicy": "projects/p/global/securityPolicies/armor-1"}},
            {"asset_type": "compute.googleapis.com/SecurityPolicy",
             "name": "//compute.googleapis.com/projects/p/global/securityPolicies/armor-1",
             "data": {"name": "armor-1", "type": "CLOUD_ARMOR"}},
            {"asset_type": "compute.googleapis.com/InstanceGroup",
             "name": "//compute.googleapis.com/projects/p/zones/us-central1-a/instanceGroups/ig-1",
             "data": {"name": "ig-1", "zone": "us-central1-a"}},
            {"asset_type": "compute.googleapis.com/Instance",
             "name": "//compute.googleapis.com/projects/p/zones/us-central1-a/instances/example-vm",
             "data": {"name": "example-vm", "status": "RUNNING",
                      "machineType": "zones/us-central1-a/machineTypes/n2d-highmem-8",
                      "confidentialInstanceConfig": {"enableConfidentialCompute": True},
                      "zone": "us-central1-a"}},
        ]

        result = build_graph("test-project")
        nodes = result["nodes"]
        edges = result["edges"]

        assert len(nodes) == 7
        node_ids = {n.id for n in nodes}
        assert "fr-lb-rule" in node_ids
        assert "proxy-proxy-1" in node_ids
        assert "urlmap-map-1" in node_ids
        assert "bs-backend-1" in node_ids
        assert "sp-armor-1" in node_ids
        assert "ig-ig-1" in node_ids
        assert "vm-example-vm" in node_ids

        # Verify chain: FR -> proxy -> urlmap -> BS -> IG -> VM
        edge_pairs = [(e.source, e.target) for e in edges]
        assert ("fr-lb-rule", "proxy-proxy-1") in edge_pairs
        assert ("proxy-proxy-1", "urlmap-map-1") in edge_pairs
        assert ("urlmap-map-1", "bs-backend-1") in edge_pairs
        assert ("bs-backend-1", "ig-ig-1") in edge_pairs
        assert ("bs-backend-1", "sp-armor-1") in edge_pairs
        assert ("ig-ig-1", "vm-example-vm") in edge_pairs

        # VM should be healthy (RUNNING)
        vm_node = [n for n in nodes if n.id == "vm-example-vm"][0]
        assert vm_node.status == "healthy"
        assert vm_node.metrics["confidential"] is True

    @patch("src.discovery.gcp_assets._check_permissions", return_value=False)
    def test_disabled_returns_empty(self, _):
        from src.discovery.gcp_assets import build_graph
        result = build_graph("test-project")
        assert result == {"nodes": [], "edges": []}

    @patch("src.discovery.gcp_assets._resolve_ig_members", return_value=[])
    @patch("src.discovery.gcp_assets._check_permissions", return_value=True)
    @patch("src.discovery.gcp_assets._list_assets", return_value=[])
    def test_empty_project(self, mock_list, mock_perm, mock_ig):
        from src.discovery.gcp_assets import build_graph
        result = build_graph("empty-project")
        assert result["nodes"] == []
        assert result["edges"] == []


class TestDiscover:
    def setup_method(self):
        _reset_module()

    @patch("src.discovery.gcp_assets.build_graph")
    def test_caches_result(self, mock_build):
        from src.discovery.gcp_assets import discover, get_cached_graph
        from src.models.topology import Node
        mock_build.return_value = {
            "nodes": [Node(id="vm-1", label="vm-1", type="vm", status="healthy")],
            "edges": [],
        }
        result = discover("test-project")
        assert result["timestamp"] is not None
        assert len(result["nodes"]) == 1

        cached = get_cached_graph()
        assert cached["timestamp"] is not None

    @patch("src.discovery.gcp_assets.build_graph", side_effect=Exception("API down"))
    def test_failure_keeps_old_cache(self, mock_build):
        from src.discovery.gcp_assets import discover, get_cached_graph
        discover("test-project")
        cached = get_cached_graph()
        # Cache stays at default (empty) — no crash
        assert cached["nodes"] == []
