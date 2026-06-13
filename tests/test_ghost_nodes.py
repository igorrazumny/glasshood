# File: tests/test_ghost_nodes.py
# Purpose: Verify config-driven GPU topology — no ghost nodes showing healthy

import unittest
from unittest.mock import patch, MagicMock

from src.models.topology import Node, Topology


class TestProbeHealth(unittest.TestCase):
    """Test the health probing function for GPU/model nodes."""

    def test_healthy_endpoint(self):
        from src.api.routes.topology import _probe_health
        mock_resp = MagicMock(status_code=200)
        with patch("httpx.get", return_value=mock_resp):
            self.assertEqual(_probe_health("http://vllm:8000/health"), "healthy")

    def test_degraded_endpoint(self):
        from src.api.routes.topology import _probe_health
        mock_resp = MagicMock(status_code=503)
        with patch("httpx.get", return_value=mock_resp):
            self.assertEqual(_probe_health("http://vllm:8000/health"), "degraded")

    def test_unreachable_endpoint(self):
        from src.api.routes.topology import _probe_health
        with patch("httpx.get", side_effect=Exception("Connection refused")):
            self.assertEqual(_probe_health("http://vllm:8000/health"), "offline")


class TestGpuNodeEnrichment(unittest.TestCase):
    """GPU nodes with status: auto get health-probed or show offline."""

    def _make_nodes(self, gpu_status="auto", health_url=""):
        return [
            Node(id="gpu_h100", label="H100", type="gpu", status=gpu_status,
                 metrics={"health_url": health_url, "spot": True}),
        ]

    @patch("src.api.routes.topology.coldvault")
    @patch("src.api.routes.topology.gcp_monitoring")
    @patch("src.api.routes.topology.gcs_bucket")
    def test_gpu_auto_no_health_url_becomes_offline(self, mock_gcs, mock_mon, mock_cv):
        """GPU with status: auto and empty health_url → offline."""
        mock_cv.get_health.return_value = {"status": "healthy"}
        mock_cv.get_metrics.return_value = {"components": {}, "system": {}}
        mock_cv.is_stale.return_value = False
        mock_mon.get_stats.return_value = {}

        from src.api.routes.topology import _enrich_nodes
        nodes = self._make_nodes(gpu_status="auto", health_url="")
        _enrich_nodes(nodes, [])
        self.assertEqual(nodes[0].status, "offline")

    @patch("src.api.routes.topology.coldvault")
    @patch("src.api.routes.topology.gcp_monitoring")
    @patch("src.api.routes.topology.gcs_bucket")
    @patch("httpx.get")
    def test_gpu_auto_with_health_url_probed(self, mock_get, mock_gcs, mock_mon, mock_cv):
        """GPU with health_url gets probed and shows healthy."""
        mock_cv.get_health.return_value = {"status": "healthy"}
        mock_cv.get_metrics.return_value = {"components": {}, "system": {}}
        mock_cv.is_stale.return_value = False
        mock_mon.get_stats.return_value = {}
        mock_get.return_value = MagicMock(status_code=200)

        from src.api.routes.topology import _enrich_nodes
        nodes = self._make_nodes(gpu_status="auto", health_url="http://vllm:8000/health")
        _enrich_nodes(nodes, [])
        self.assertEqual(nodes[0].status, "healthy")

    def test_planned_gpu_not_in_overall_status(self):
        """Planned GPU nodes don't affect overall_status."""
        topo = Topology(nodes=[
            Node(id="nginx", label="nginx", type="nginx", status="healthy"),
            Node(id="gpu_h200", label="H200", type="gpu", status="planned"),
        ])
        topo.update_overall_status()
        self.assertEqual(topo.overall_status, "healthy")

    def test_offline_gpu_not_in_overall_status(self):
        """Offline GPU nodes (spot down) don't affect overall_status."""
        topo = Topology(nodes=[
            Node(id="nginx", label="nginx", type="nginx", status="healthy"),
            Node(id="gpu_h100", label="H100", type="gpu", status="offline"),
        ])
        topo.update_overall_status()
        self.assertEqual(topo.overall_status, "healthy")


class TestSelfHostedModelStatus(unittest.TestCase):
    """Self-hosted models must not show green when GPU is offline."""

    def test_model_discovery_uses_auto_not_deployed(self):
        """model_discovery must set status='auto', not 'deployed'."""
        from src.discovery.model_discovery import discover_models
        nodes, edges = discover_models("config/model_settings.yaml")
        self_hosted = [n for n in nodes if n.metrics.get("mode") == "self-hosted"]
        assert len(self_hosted) > 0, "Expected self-hosted models in config"
        for node in self_hosted:
            assert node.status == "auto", (
                f"Self-hosted model {node.id} has status='{node.status}', "
                f"expected 'auto' — must be resolved by enrichment"
            )

    def test_self_hosted_has_health_url(self):
        """Self-hosted models must have health_url for enrichment to resolve."""
        from src.discovery.model_discovery import discover_models
        nodes, edges = discover_models("config/model_settings.yaml")
        self_hosted = [n for n in nodes if n.metrics.get("mode") == "self-hosted"]
        for node in self_hosted:
            assert "health_url" in node.metrics, (
                f"Self-hosted model {node.id} missing health_url metric"
            )

    @patch("src.api.routes.topology.coldvault")
    @patch("src.api.routes.topology.gcp_monitoring")
    @patch("src.api.routes.topology.gcs_bucket")
    def test_gpu_offline_when_no_health_url(self, mock_gcs, mock_mon, mock_cv):
        """GPU node with empty health_url resolves to offline."""
        mock_cv.get_health.return_value = {"status": "healthy"}
        mock_cv.get_metrics.return_value = {"components": {}, "system": {}}
        mock_cv.is_stale.return_value = False
        mock_mon.get_stats.return_value = {}

        from src.api.routes.topology import _enrich_nodes
        nodes = [
            Node(id="gpu_h100_spot", label="H100", type="gpu", status="auto",
                 metrics={"health_url": ""}),
        ]
        _enrich_nodes(nodes, [])
        self.assertEqual(nodes[0].status, "offline")

    def test_gpu_label_says_h100_not_a100(self):
        """Self-hosted models must reference H100, not stale A100."""
        from src.discovery.model_discovery import discover_models
        nodes, _ = discover_models("config/model_settings.yaml")
        self_hosted = [n for n in nodes if n.metrics.get("mode") == "self-hosted"]
        for node in self_hosted:
            gpu = node.metrics.get("gpu", "")
            assert "A100" not in gpu, (
                f"Self-hosted model {node.id} still references A100: '{gpu}'"
            )


class TestNoHardcodedStatus(unittest.TestCase):
    """Verify topology_overrides.yaml has no hardcoded healthy status."""

    def test_no_hardcoded_healthy_gpu(self):
        """No GPU node should have status: healthy in config."""
        import yaml
        with open("config/topology_overrides.yaml") as f:
            config = yaml.safe_load(f)
        for node in config.get("nodes", []):
            if node.get("type") == "gpu":
                self.assertNotEqual(
                    node.get("status"), "healthy",
                    f"GPU node {node['id']} has hardcoded status: healthy"
                )
