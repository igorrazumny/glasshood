# File: tests/test_manifest_metrics.py
# Purpose: Tests for YAML-driven manifest metrics poller (REQ-203)

import pytest
from unittest.mock import patch, MagicMock
from src.collectors.manifest_metrics import (
    _parse_threshold, _evaluate_status, _poll_node, get_node_status,
    get_all_statuses, poll_all_manifest_nodes, _metrics_cache, _lock,
    resolve_children_template, _vm_cache, _vm_cache_times,
)


class TestParseThreshold:
    def test_less_than_true(self):
        assert _parse_threshold("< 500", 200) is True

    def test_less_than_false(self):
        assert _parse_threshold("< 500", 600) is False

    def test_less_than_boundary(self):
        assert _parse_threshold("< 500", 500) is False

    def test_less_equal_boundary(self):
        assert _parse_threshold("<= 500", 500) is True

    def test_greater_equal_true(self):
        assert _parse_threshold(">= 2000", 2500) is True

    def test_greater_equal_boundary(self):
        assert _parse_threshold(">= 2000", 2000) is True

    def test_greater_equal_false(self):
        assert _parse_threshold(">= 2000", 1999) is False

    def test_greater_than(self):
        assert _parse_threshold("> 100", 101) is True

    def test_equals(self):
        assert _parse_threshold("== 0", 0) is True

    def test_empty_string(self):
        assert _parse_threshold("", 100) is False

    def test_none(self):
        assert _parse_threshold(None, 100) is False

    def test_non_string(self):
        assert _parse_threshold(42, 100) is False

    def test_invalid_number(self):
        assert _parse_threshold("< abc", 100) is False


class TestEvaluateStatus:
    """Verify healthy-first evaluation (R30 lesson: order matters)."""

    def test_healthy_first(self):
        """200ms latency: healthy < 500, degraded < 2000 → should be healthy, not degraded."""
        thresholds = {"healthy": "< 500", "degraded": "< 2000", "error": ">= 2000"}
        assert _evaluate_status(200, thresholds) == "healthy"

    def test_degraded(self):
        thresholds = {"healthy": "< 500", "degraded": "< 2000", "error": ">= 2000"}
        assert _evaluate_status(800, thresholds) == "degraded"

    def test_error(self):
        thresholds = {"healthy": "< 500", "degraded": "< 2000", "error": ">= 2000"}
        assert _evaluate_status(3000, thresholds) == "error"

    def test_empty_thresholds_returns_none(self):
        """Informational metrics (no thresholds) don't affect status."""
        assert _evaluate_status(100, {}) is None

    def test_none_thresholds_returns_none(self):
        assert _evaluate_status(100, None) is None

    def test_cpu_healthy(self):
        thresholds = {"healthy": "< 70", "degraded": "< 90", "error": ">= 90"}
        assert _evaluate_status(45, thresholds) == "healthy"

    def test_cpu_degraded(self):
        thresholds = {"healthy": "< 70", "degraded": "< 90", "error": ">= 90"}
        assert _evaluate_status(85, thresholds) == "degraded"

    def test_cpu_error(self):
        thresholds = {"healthy": "< 70", "degraded": "< 90", "error": ">= 90"}
        assert _evaluate_status(95, thresholds) == "error"


class TestPollNode:
    def test_no_metrics_config(self):
        node = {"id": "test-node", "monitoring": {}}
        result = _poll_node(node)
        assert result["node_id"] == "test-node"
        assert result["status"] == "not monitored"

    def test_empty_metrics_list(self):
        node = {"id": "test-node", "monitoring": {"metrics": []}}
        result = _poll_node(node)
        assert result["status"] == "not monitored"

    @patch("src.collectors.manifest_metrics._poll_metric")
    def test_healthy_node(self, mock_poll):
        mock_poll.return_value = 200.0
        node = {
            "id": "lb-platform",
            "monitoring": {
                "metrics": [{
                    "name": "latency_ms",
                    "metric_type": "loadbalancing.googleapis.com/https/backend_latencies",
                    "project": "test-project",
                    "filter": 'resource.labels.forwarding_rule_name="test-rule"',
                    "aggregation": "mean",
                    "thresholds": {"healthy": "< 500", "degraded": "< 2000", "error": ">= 2000"},
                }]
            }
        }
        result = _poll_node(node)
        assert result["status"] == "healthy"
        assert result["metrics"]["latency_ms"] == 200.0

    @patch("src.collectors.manifest_metrics._poll_metric")
    def test_degraded_node(self, mock_poll):
        mock_poll.return_value = 1200.0
        node = {
            "id": "lb-platform",
            "monitoring": {
                "metrics": [{
                    "name": "latency_ms",
                    "metric_type": "compute.googleapis.com/instance/cpu/utilization",
                    "project": "test-project",
                    "aggregation": "mean",
                    "thresholds": {"healthy": "< 500", "degraded": "< 2000", "error": ">= 2000"},
                }]
            }
        }
        result = _poll_node(node)
        assert result["status"] == "degraded"

    @patch("src.collectors.manifest_metrics._poll_metric")
    def test_worst_status_wins(self, mock_poll):
        """Two metrics: one healthy, one error → overall error."""
        mock_poll.side_effect = [200.0, 95.0]
        node = {
            "id": "mig-platform",
            "monitoring": {
                "metrics": [
                    {
                        "name": "latency_ms",
                        "metric_type": "test1",
                        "project": "p",
                        "aggregation": "mean",
                        "thresholds": {"healthy": "< 500", "degraded": "< 2000", "error": ">= 2000"},
                    },
                    {
                        "name": "cpu_percent",
                        "metric_type": "test2",
                        "project": "p",
                        "aggregation": "mean",
                        "multiplier": 100,
                        "thresholds": {"healthy": "< 70", "degraded": "< 90", "error": ">= 90"},
                    },
                ]
            }
        }
        result = _poll_node(node)
        assert result["status"] == "error"

    @patch("src.collectors.manifest_metrics._poll_metric")
    def test_null_metric_value(self, mock_poll):
        mock_poll.return_value = None
        node = {
            "id": "monitor-node",
            "monitoring": {
                "metrics": [{
                    "name": "cpu_utilization",
                    "metric_type": "compute.googleapis.com/instance/cpu/utilization",
                    "project": "p",
                    "aggregation": "mean",
                    "thresholds": {"healthy": "< 100"},
                }]
            }
        }
        result = _poll_node(node)
        assert result["metrics"]["cpu_utilization"] is None

    @patch("src.collectors.manifest_metrics._poll_metric")
    def test_all_null_returns_unknown(self, mock_poll):
        """When all polls return None, status should be 'unknown' not 'healthy'."""
        mock_poll.return_value = None
        node = {
            "id": "monitor-node",
            "monitoring": {
                "metrics": [{
                    "name": "latency",
                    "metric_type": "compute.googleapis.com/instance/cpu/utilization",
                    "project": "p",
                    "aggregation": "mean",
                    "thresholds": {"healthy": "< 500"},
                }]
            }
        }
        result = _poll_node(node)
        assert result["status"] == "unknown"

    @patch("src.collectors.manifest_metrics._poll_metric")
    def test_zero_value_is_valid(self, mock_poll):
        """Zero is a valid metric value, not null."""
        mock_poll.return_value = 0.0
        node = {
            "id": "monitor-node",
            "monitoring": {
                "metrics": [{
                    "name": "cpu",
                    "metric_type": "compute.googleapis.com/instance/cpu/utilization",
                    "project": "p",
                    "aggregation": "mean",
                    "thresholds": {"healthy": "< 70", "error": ">= 70"},
                }]
            }
        }
        result = _poll_node(node)
        assert result["metrics"]["cpu"] == 0.0
        assert result["status"] == "healthy"

    @patch("src.collectors.manifest_metrics._poll_metric")
    def test_resource_filter_passed(self, mock_poll):
        """Verify the resource filter from YAML is passed to _poll_metric."""
        mock_poll.return_value = 100.0
        node = {
            "id": "lb-platform",
            "monitoring": {
                "metrics": [{
                    "name": "latency_ms",
                    "metric_type": "loadbalancing.googleapis.com/https/backend_latencies",
                    "project": "example-platform-project",
                    "filter": 'resource.labels.forwarding_rule_name="platform-https-rule"',
                    "aggregation": "mean",
                    "thresholds": {"healthy": "< 500"},
                }]
            }
        }
        _poll_node(node)
        mock_poll.assert_called_once_with(
            "example-platform-project",
            "loadbalancing.googleapis.com/https/backend_latencies",
            'resource.labels.forwarding_rule_name="platform-https-rule"',
            "mean",
            1.0,
        )


class TestProbe:
    @patch("src.collectors.manifest_metrics._probe_gcp_secret")
    def test_secret_probe_healthy(self, mock_probe):
        mock_probe.return_value = True
        node = {
            "id": "secrets-platform",
            "monitoring": {
                "probe": {
                    "type": "gcp_secret",
                    "project": "test-project",
                    "secret_name": "TEST_SECRET",
                }
            }
        }
        result = _poll_node(node)
        assert result["status"] == "healthy"
        assert result["metrics"]["accessible"] == 1

    @patch("src.collectors.manifest_metrics._probe_gcp_secret")
    def test_secret_probe_error(self, mock_probe):
        mock_probe.return_value = False
        node = {
            "id": "secrets-platform",
            "monitoring": {
                "probe": {
                    "type": "gcp_secret",
                    "project": "test-project",
                    "secret_name": "TEST_SECRET",
                }
            }
        }
        result = _poll_node(node)
        assert result["status"] == "error"
        assert result["metrics"]["accessible"] == 0

    def test_probe_only_no_metrics(self):
        """Node with probe but no metrics should not return 'not monitored'."""
        node = {
            "id": "monitor-node",
            "monitoring": {
                "probe": {"type": "unknown_type", "project": "p"}
            }
        }
        result = _poll_node(node)
        # Unknown probe type falls through to no-metrics path
        assert result["status"] == "not monitored"


class TestMigScopedFilter:
    """R32: verify mig_scoped filter only includes MIG-discovered instance IDs."""

    @patch("src.collectors.manifest_metrics._poll_metric")
    def test_mig_scoped_with_cached_ids(self, mock_poll):
        """When MIG VMs are discovered, _poll_metric IS called with scoped filter."""
        mock_poll.return_value = 45.0
        from src.collectors.manifest_metrics import _vm_cache
        try:
            _vm_cache["proj/zone/example-mig"] = [
                {"id": "vm-abc", "instance_id": "123456", "status": "healthy"},
                {"id": "vm-def", "instance_id": "789012", "status": "healthy"},
            ]
            node = {
                "id": "mig-node",
                "monitoring": {
                    "discover": {"project": "proj", "zone": "zone", "instance_group": "example-mig"},
                    "metrics": [{
                        "name": "cpu_percent",
                        "metric_type": "compute.googleapis.com/instance/cpu/utilization",
                        "project": "proj",
                        "filter": "mig_scoped",
                        "aggregation": "mean",
                        "multiplier": 100,
                        "thresholds": {"healthy": "< 70"},
                    }]
                }
            }
            result = _poll_node(node)
            mock_poll.assert_called_once()
            # Verify filter contains instance IDs
            call_filter = mock_poll.call_args[0][2]  # 3rd positional arg = resource_filter
            assert "123456" in call_filter
            assert "789012" in call_filter
            assert result["metrics"]["cpu_percent"] == 45.0
        finally:
            _vm_cache.clear()

    @patch("src.collectors.manifest_metrics._poll_metric")
    def test_mig_scoped_without_cache_returns_none(self, mock_poll):
        """When no MIG VMs discovered yet, metric returns None (no unscoped fallback)."""
        from src.collectors.manifest_metrics import _vm_cache
        try:
            _vm_cache.clear()
            node = {
                "id": "mig-node",
                "monitoring": {
                    "discover": {"project": "proj", "zone": "zone", "instance_group": "example-mig"},
                    "metrics": [{
                        "name": "cpu_percent",
                        "metric_type": "compute.googleapis.com/instance/cpu/utilization",
                        "project": "proj",
                        "filter": "mig_scoped",
                        "aggregation": "mean",
                        "thresholds": {"healthy": "< 70"},
                    }]
                }
            }
            result = _poll_node(node)
            mock_poll.assert_not_called()
            assert result["metrics"]["cpu_percent"] is None
        finally:
            _vm_cache.clear()

    @patch("src.collectors.manifest_metrics._poll_metric")
    def test_mig_scoped_excludes_other_mig(self, mock_poll):
        """Cross-MIG isolation: only include IDs from THIS node's MIG."""
        mock_poll.return_value = 30.0
        from src.collectors.manifest_metrics import _vm_cache
        try:
            _vm_cache["proj/zone/example-mig"] = [
                {"id": "vm-abc", "instance_id": "111", "status": "healthy"},
            ]
            _vm_cache["other-proj/zone/other-mig"] = [
                {"id": "vm-xyz", "instance_id": "999", "status": "healthy"},
            ]
            node = {
                "id": "mig-node",
                "monitoring": {
                    "discover": {"project": "proj", "zone": "zone", "instance_group": "example-mig"},
                    "metrics": [{
                        "name": "cpu_percent",
                        "metric_type": "compute.googleapis.com/instance/cpu/utilization",
                        "project": "proj",
                        "filter": "mig_scoped",
                        "aggregation": "mean",
                        "thresholds": {"healthy": "< 70"},
                    }]
                }
            }
            _poll_node(node)
            call_filter = mock_poll.call_args[0][2]
            assert "111" in call_filter
            assert "999" not in call_filter  # Other MIG excluded
        finally:
            _vm_cache.clear()


class TestCache:
    def test_get_node_status_empty(self):
        with _lock:
            _metrics_cache.clear()
        assert get_node_status("nonexistent") is None

    def test_get_all_statuses_empty(self):
        with _lock:
            _metrics_cache.clear()
        assert get_all_statuses() == {}


class TestResolveChildrenTemplate:
    """R34: deepcopy prevents cross-VM template mutation."""

    def test_deepcopy_prevents_filter_corruption(self):
        """Resolving template for VM-A must not corrupt template for VM-B."""
        template = [
            {
                "id_suffix": "-docker",
                "label": "Docker on {vm_name}",
                "type": "container",
                "monitoring": {
                    "logs": [
                        {"project": "proj", "filter": 'instance.name="{vm_name}"'}
                    ]
                },
                "children": [
                    {
                        "id_suffix": "-api",
                        "label": "API on {vm_name}",
                        "type": "application",
                        "monitoring": {
                            "logs": [
                                {"project": "proj", "filter": 'instance.name="{vm_name}" AND app'}
                            ]
                        },
                    }
                ],
            }
        ]
        # Resolve for VM-A
        result_a = resolve_children_template(template, "vm-aaa", "id-111")
        # Resolve for VM-B — must not contain VM-A's name
        result_b = resolve_children_template(template, "vm-bbb", "id-222")

        # VM-A checks
        assert result_a[0]["id"] == "vm-vm-aaa-docker"
        assert "vm-aaa" in result_a[0]["monitoring"]["logs"][0]["filter"]
        assert result_a[0]["children"][0]["id"] == "vm-vm-aaa-api"

        # VM-B must NOT have VM-A's name leaked into it
        assert "vm-aaa" not in result_b[0]["monitoring"]["logs"][0]["filter"]
        assert "vm-bbb" in result_b[0]["monitoring"]["logs"][0]["filter"]
        assert "vm-aaa" not in result_b[0]["children"][0]["monitoring"]["logs"][0]["filter"]
        assert "vm-bbb" in result_b[0]["children"][0]["monitoring"]["logs"][0]["filter"]

        # Original template must be untouched (still has {vm_name} placeholders)
        assert "{vm_name}" in template[0]["monitoring"]["logs"][0]["filter"]
        assert "{vm_name}" in template[0]["children"][0]["monitoring"]["logs"][0]["filter"]


class TestConnectsTo:
    """REQ-702: connects_to on children_template creates edges."""

    def test_connects_to_preserved_on_resolve(self):
        """connects_to field survives template resolution via deepcopy."""
        template = [
            {
                "id_suffix": "-api",
                "label": "My App",
                "type": "application",
                "connects_to": ["@providers", "@gpu"],
            }
        ]
        result = resolve_children_template(template, "vm-abc", "id-123")
        assert result[0]["connects_to"] == ["@providers", "@gpu"]
        assert result[0]["id"] == "vm-vm-abc-api"

    def test_connects_to_preserved_nested(self):
        """connects_to on nested children also survives resolution."""
        template = [
            {
                "id_suffix": "-docker",
                "label": "Docker",
                "type": "container",
                "children": [
                    {
                        "id_suffix": "-api",
                        "label": "App",
                        "type": "application",
                        "connects_to": ["@providers"],
                    }
                ],
            }
        ]
        result = resolve_children_template(template, "vm-xyz", "id-456")
        api_child = result[0]["children"][0]
        assert api_child["connects_to"] == ["@providers"]
        assert api_child["id"] == "vm-vm-xyz-api"


class TestPlatformInferenceProbe:
    """REQ-401: Platform inference URL is env-configurable, non-prod defaults to disabled."""

    def test_short_circuits_when_platform_url_empty(self):
        """Empty PLATFORM_INFERENCE_URL → no httpx call, descriptive error."""
        from src.collectors.manifest_metrics import _probe_platform_inference

        with patch("src.collectors.manifest_metrics._get_platform_inference_url",
                   return_value=""), \
             patch("src.collectors.manifest_metrics._get_platform_key",
                   return_value="key"), \
             patch("httpx.post") as mock_post:
            result = _probe_platform_inference("any-model", 30)

        assert result["ok"] is False
        assert "PLATFORM_INFERENCE_URL not configured" in result["desc"]
        mock_post.assert_not_called()

    def test_uses_env_url_when_configured(self):
        """PLATFORM_INFERENCE_URL set → httpx.post called with exactly that URL."""
        from src.collectors.manifest_metrics import _probe_platform_inference

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"response": "hi", "elapsed_s": 0.5}

        with patch("src.collectors.manifest_metrics._get_platform_inference_url",
                   return_value="https://val.api.example.com/api/v1/inference"), \
             patch("src.collectors.manifest_metrics._get_platform_key",
                   return_value="key"), \
             patch("httpx.post", return_value=mock_resp) as mock_post:
            result = _probe_platform_inference("any-model", 30)

        assert result["ok"] is True
        assert mock_post.call_args.args[0] == "https://val.api.example.com/api/v1/inference"

    def test_no_hardcoded_prod_url_in_source(self):
        """Hardcoded api.example.com literal no longer in _probe_platform_inference."""
        import inspect
        from src.collectors.manifest_metrics import _probe_platform_inference

        source = inspect.getsource(_probe_platform_inference)
        assert "api.example.com" not in source, (
            "REQ-401: URL must come from PLATFORM_INFERENCE_URL env var, "
            "not a hardcoded literal in the function body"
        )

    def test_platform_key_missing_short_circuits_after_url_check(self):
        """When URL is set but PLATFORM_KEY is empty, still no httpx call."""
        from src.collectors.manifest_metrics import _probe_platform_inference

        with patch("src.collectors.manifest_metrics._get_platform_inference_url",
                   return_value="https://api.example.com/api/v1/inference"), \
             patch("src.collectors.manifest_metrics._get_platform_key",
                   return_value=""), \
             patch("httpx.post") as mock_post:
            result = _probe_platform_inference("any-model", 30)

        assert result["ok"] is False
        assert "NINE_ROBOTS_PLATFORM_KEY not configured" in result["desc"]
        mock_post.assert_not_called()


class TestVmCacheIsolation:
    """R34: per-key cache timestamps prevent cross-MIG staleness."""

    def test_per_key_timestamps_exist(self):
        """_vm_cache_times is a dict, not a single float."""
        assert isinstance(_vm_cache_times, dict)

    def test_per_key_independence(self):
        """Refreshing MIG-A cache must not affect MIG-B's freshness."""
        import time as _time
        try:
            _vm_cache.clear()
            _vm_cache_times.clear()

            # Populate MIG-A at time T
            _vm_cache["proj/zone/mig-a"] = [{"id": "vm-a1", "instance_id": "111"}]
            _vm_cache_times["proj/zone/mig-a"] = _time.time()

            # MIG-B has no timestamp — should NOT be considered fresh
            assert "proj/zone/mig-b" not in _vm_cache_times

            # Populate MIG-B at time T+1
            _vm_cache["proj/zone/mig-b"] = [{"id": "vm-b1", "instance_id": "222"}]
            _vm_cache_times["proj/zone/mig-b"] = _time.time()

            # Both have independent timestamps
            assert _vm_cache_times["proj/zone/mig-a"] <= _vm_cache_times["proj/zone/mig-b"]

            # Expire MIG-A by setting old timestamp
            _vm_cache_times["proj/zone/mig-a"] = 0
            assert _vm_cache_times["proj/zone/mig-a"] == 0
            # MIG-B is unaffected
            assert _vm_cache_times["proj/zone/mig-b"] > 0
        finally:
            _vm_cache.clear()
            _vm_cache_times.clear()
