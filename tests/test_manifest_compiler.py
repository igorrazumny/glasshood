# File: tests/test_manifest_compiler.py
# Purpose: Tests for manifest compiler (Inherit → Hydrate → Validate → Verify)

import socket
from unittest.mock import patch, MagicMock

from src.manifest_compiler import (
    compile_manifest, compile_all, _verify_http_probe, _verify_gcp_secret,
    _verify_logs_accessible, _verify_gcp_resource_exists, _verify_node,
    _is_safe_url, reset_verification, get_verification_status,
    MANDATORY_TYPES, OPTIONAL_TYPES,
)


class TestInherit:
    """Step 1: header metadata auto-injected into every node."""

    def test_inherits_project_id(self):
        manifest = {
            "project_id": "my-project",
            "product": "platform",
            "environment": "prod",
            "solution": "9Robots Platform",
            "company": "9RobotsAI",
            "nodes": [{"id": "lb-platform", "type": "load_balancer"}],
            "edges": [],
        }
        result = compile_manifest(manifest)
        node = result["nodes"][0]
        assert node["project_id"] == "my-project"
        assert node["project"] == "platform"
        assert node["env"] == "prod"
        assert node["solution"] == "9Robots Platform"
        assert node["company"] == "9RobotsAI"

    def test_does_not_overwrite_explicit(self):
        manifest = {
            "project_id": "header-project",
            "product": "platform",
            "environment": "prod",
            "solution": "Platform",
            "company": "9RobotsAI",
            "nodes": [{"id": "node-1", "type": "mig", "project_id": "override-project"}],
            "edges": [],
        }
        result = compile_manifest(manifest)
        assert result["nodes"][0]["project_id"] == "override-project"


class TestHydrate:
    """Step 2 — REQ-212: node-type-registry fills missing monitoring.logs."""

    def test_auto_assigns_mig_logs(self):
        manifest = {
            "project_id": "proj",
            "product": "test",
            "environment": "prod",
            "nodes": [{"id": "mig-1", "type": "mig"}],
            "edges": [],
        }
        result = compile_manifest(manifest)
        logs = result["nodes"][0].get("monitoring", {}).get("logs")
        assert logs is not None
        assert logs[0]["project"] == "proj"
        assert "gce_instance" in logs[0]["filter"]

    def test_auto_assigns_secret_logs(self):
        manifest = {
            "project_id": "proj",
            "product": "test",
            "environment": "prod",
            "nodes": [{"id": "sec-1", "type": "secret"}],
            "edges": [],
        }
        result = compile_manifest(manifest)
        logs = result["nodes"][0]["monitoring"]["logs"]
        assert "secretmanager" in logs[0]["filter"]

    def test_auto_assigns_cloud_run_logs_with_service_name(self):
        manifest = {
            "project_id": "proj",
            "product": "test",
            "environment": "prod",
            "nodes": [{"id": "gh-cloudrun", "type": "cloud_run"}],
            "edges": [],
        }
        result = compile_manifest(manifest)
        logs = result["nodes"][0]["monitoring"]["logs"]
        assert "cloud_run_revision" in logs[0]["filter"]
        assert "cloudrun" in logs[0]["filter"]

    def test_auto_assigns_load_balancer_logs(self):
        """REQ-212: load_balancer nodes get gce_instance default to show backend traffic."""
        manifest = {
            "project_id": "proj",
            "product": "test",
            "environment": "prod",
            "nodes": [{"id": "lb-1", "type": "load_balancer"}],
            "edges": [],
        }
        result = compile_manifest(manifest)
        logs = result["nodes"][0]["monitoring"]["logs"]
        assert "gce_instance" in logs[0]["filter"]

    def test_does_not_overwrite_explicit_logs(self):
        manifest = {
            "project_id": "proj",
            "product": "test",
            "environment": "prod",
            "nodes": [{
                "id": "mig-1",
                "type": "mig",
                "monitoring": {
                    "logs": [{"project": "custom", "filter": "custom-filter"}]
                },
            }],
            "edges": [],
        }
        result = compile_manifest(manifest)
        logs = result["nodes"][0]["monitoring"]["logs"]
        assert logs[0]["project"] == "custom"
        assert logs[0]["filter"] == "custom-filter"

    def test_provider_gets_no_default_logs(self):
        """Provider nodes are opt-in — they don't appear in LOG_DEFAULTS by design."""
        manifest = {
            "project_id": "proj",
            "product": "test",
            "environment": "prod",
            "nodes": [{"id": "prov-1", "type": "provider"}],
            "edges": [],
        }
        result = compile_manifest(manifest)
        monitoring = result["nodes"][0].get("monitoring", {})
        assert not monitoring.get("logs")

    def test_log_defaults_registry_present(self):
        """REQ-212: LOG_DEFAULTS dict is part of the public surface for the registry."""
        import src.manifest_compiler as mod
        assert hasattr(mod, "LOG_DEFAULTS")
        assert "load_balancer" in mod.LOG_DEFAULTS
        assert "mig" in mod.LOG_DEFAULTS


class TestValidate:
    """Step 3: warnings for config gaps."""

    def test_warns_orphan_node(self):
        manifest = {
            "project_id": "proj",
            "product": "test",
            "environment": "prod",
            "nodes": [{"id": "orphan-1", "type": "mig"}],
            "edges": [],
        }
        result = compile_manifest(manifest)
        assert any("orphan" in w.lower() for w in result["_warnings"])

    def test_no_orphan_warning_for_connected_node(self):
        manifest = {
            "project_id": "proj",
            "product": "test",
            "environment": "prod",
            "nodes": [
                {"id": "lb-1", "type": "load_balancer"},
                {"id": "mig-1", "type": "mig"},
            ],
            "edges": [{"source": "lb-1", "target": "mig-1"}],
        }
        result = compile_manifest(manifest)
        assert not any("orphan" in w.lower() for w in result["_warnings"])

    def test_no_orphan_warning_for_providers(self):
        manifest = {
            "project_id": "proj",
            "product": "test",
            "environment": "prod",
            "nodes": [{"id": "prov-1", "type": "provider"}],
            "edges": [],
        }
        result = compile_manifest(manifest)
        assert not any("orphan" in w.lower() for w in result["_warnings"])

    def test_compiled_flag_set(self):
        manifest = {
            "project_id": "proj",
            "product": "test",
            "environment": "prod",
            "nodes": [],
            "edges": [],
        }
        result = compile_manifest(manifest)
        assert result["_compiled"] is True


class TestCompileAll:
    def test_compiles_multiple(self):
        manifests = [
            {"project_id": "p1", "product": "a", "environment": "prod",
             "nodes": [{"id": "n1", "type": "mig"}], "edges": []},
            {"project_id": "p2", "product": "b", "environment": "val",
             "nodes": [{"id": "n2", "type": "secret"}], "edges": []},
        ]
        results = compile_all(manifests)
        assert len(results) == 2
        assert results[0]["nodes"][0]["project_id"] == "p1"
        assert results[1]["nodes"][0]["project_id"] == "p2"
        assert all(r["_compiled"] for r in results)


# === NESTED CHILDREN TESTS ===


class TestNestedChildren:
    """Children compilation — recursive inherit/hydrate for nested nodes."""

    def test_children_inherit_header(self):
        manifest = {
            "project_id": "proj", "product": "platform", "environment": "prod",
            "solution": "Platform", "company": "9R",
            "nodes": [{
                "id": "vm-1", "type": "vm",
                "children": [
                    {"id": "vm-1-docker", "type": "container"},
                    {"id": "vm-1-app", "type": "application"},
                ],
            }],
            "edges": [],
        }
        result = compile_manifest(manifest)
        vm = result["nodes"][0]
        assert vm["project_id"] == "proj"
        assert len(vm["children"]) == 2
        assert vm["children"][0]["project_id"] == "proj"
        assert vm["children"][0]["environment"] == "prod"
        assert vm["children"][1]["id"] == "vm-1-app"

    def test_deep_nesting(self):
        manifest = {
            "project_id": "proj", "product": "test", "environment": "prod",
            "nodes": [{
                "id": "vm-1", "type": "vm",
                "children": [{
                    "id": "container-1", "type": "container",
                    "children": [
                        {"id": "app-1", "type": "application"},
                        {"id": "db-1", "type": "database"},
                    ],
                }],
            }],
            "edges": [],
        }
        result = compile_manifest(manifest)
        container = result["nodes"][0]["children"][0]
        assert len(container["children"]) == 2
        assert container["children"][0]["id"] == "app-1"
        assert container["children"][1]["project_id"] == "proj"

    def test_children_template_preserved(self):
        manifest = {
            "project_id": "proj", "product": "test", "environment": "prod",
            "nodes": [{
                "id": "mig-1", "type": "mig",
                "children_template": [
                    {"id_suffix": "-docker", "label": "Docker", "type": "container"},
                ],
            }],
            "edges": [],
        }
        result = compile_manifest(manifest)
        assert result["nodes"][0]["children_template"][0]["id_suffix"] == "-docker"


# === VERIFICATION TESTS (REQ-601) ===


# DNS mock helpers for SSRF tests (must be defined before use)
def _mock_resolve_public(host, *args, **kwargs):
    """Mock DNS resolution returning a public IP."""
    return [(2, 1, 6, '', ('93.184.216.34', 0))]


def _mock_resolve_private(host, *args, **kwargs):
    """Mock DNS resolution returning a private/loopback IP (rebinding attack)."""
    return [(2, 1, 6, '', ('169.254.169.254', 0))]


def _mock_resolve_loopback(host, *args, **kwargs):
    """Mock DNS resolution returning loopback."""
    return [(2, 1, 6, '', ('127.0.0.1', 0))]


def _mock_resolve_fail(host, *args, **kwargs):
    """Mock DNS resolution failure."""
    import socket
    raise socket.gaierror("Name resolution failed")


class TestVerifyHttpProbe:
    """HTTP endpoint probing."""

    @patch("src.manifest_compiler.socket.getaddrinfo", side_effect=_mock_resolve_public)
    @patch("httpx.get")
    def test_success(self, mock_get, mock_dns):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.elapsed.total_seconds.return_value = 0.05
        mock_get.return_value = mock_resp
        result = _verify_http_probe("https://example.com/health")
        assert result["ok"] is True
        assert result["latency_ms"] == 50
        assert result["error"] is None

    @patch("src.manifest_compiler.socket.getaddrinfo", side_effect=_mock_resolve_public)
    @patch("httpx.get")
    def test_non_200(self, mock_get, mock_dns):
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_resp.elapsed.total_seconds.return_value = 0.1
        mock_get.return_value = mock_resp
        result = _verify_http_probe("https://example.com/health")
        assert result["ok"] is False
        assert result["status_code"] == 503

    @patch("src.manifest_compiler.socket.getaddrinfo", side_effect=_mock_resolve_public)
    @patch("httpx.get")
    def test_connection_error(self, mock_get, mock_dns):
        mock_get.side_effect = Exception("Connection refused")
        result = _verify_http_probe("https://unreachable.example.com")
        assert result["ok"] is False
        assert "Connection refused" in result["error"]


class TestSsrfProtection:
    """SSRF protection for HTTP probes."""

    @patch("src.manifest_compiler.socket.getaddrinfo", side_effect=_mock_resolve_private)
    def test_blocks_metadata_endpoint(self, mock_dns):
        assert _is_safe_url("http://169.254.169.254/latest/meta-data/") is False

    @patch("src.manifest_compiler.socket.getaddrinfo", side_effect=_mock_resolve_loopback)
    def test_blocks_localhost(self, mock_dns):
        assert _is_safe_url("http://localhost:8080/admin") is False
        assert _is_safe_url("http://127.0.0.1:8080/admin") is False

    @patch("src.manifest_compiler.socket.getaddrinfo", side_effect=_mock_resolve_private)
    def test_blocks_private_ips(self, mock_dns):
        assert _is_safe_url("http://10.0.0.1/internal") is False
        assert _is_safe_url("http://192.168.1.1/admin") is False
        assert _is_safe_url("http://172.16.0.1/internal") is False

    def test_blocks_non_http_schemes(self):
        assert _is_safe_url("file:///etc/passwd") is False
        assert _is_safe_url("ftp://internal.server/data") is False
        assert _is_safe_url("gopher://evil.com") is False

    @patch("src.manifest_compiler.socket.getaddrinfo", side_effect=_mock_resolve_public)
    def test_allows_public_urls(self, mock_dns):
        assert _is_safe_url("https://api.9robots.ai/api/health") is True
        assert _is_safe_url("https://example.com/health") is True
        assert _is_safe_url("http://api.example.com/health") is True

    @patch("src.manifest_compiler.socket.getaddrinfo", side_effect=_mock_resolve_private)
    def test_blocks_dns_rebinding(self, mock_dns):
        """nip.io-style domains that resolve to internal IPs."""
        assert _is_safe_url("http://169.254.169.254.nip.io/latest/meta-data/") is False
        assert _is_safe_url("http://10.0.0.1.nip.io/internal") is False

    @patch("src.manifest_compiler.socket.getaddrinfo", side_effect=_mock_resolve_fail)
    def test_blocks_unresolvable_hosts(self, mock_dns):
        """Hosts that can't be resolved are blocked."""
        assert _is_safe_url("http://nonexistent.internal/secret") is False

    def test_blocks_ipv6_mapped_ipv4(self):
        """IPv6-mapped IPv4 addresses that resolve to private IPs."""
        def _mock_ipv6_mapped(host, *args, **kwargs):
            return [(10, 1, 6, '', ('::ffff:169.254.169.254', 0, 0, 0))]
        with patch("src.manifest_compiler.socket.getaddrinfo", side_effect=_mock_ipv6_mapped):
            assert _is_safe_url("http://evil.com/steal") is False

    def test_blocks_mixed_public_private(self):
        """If ANY resolved address is private, block (dual-stack with private addr)."""
        def _mock_mixed(host, *args, **kwargs):
            return [
                (2, 1, 6, '', ('93.184.216.34', 0)),    # public
                (10, 1, 6, '', ('::ffff:10.0.0.1', 0, 0, 0)),  # private
            ]
        with patch("src.manifest_compiler.socket.getaddrinfo", side_effect=_mock_mixed):
            assert _is_safe_url("http://dual-stack.example.com/api") is False

    def test_blocks_socket_timeout(self):
        """socket.timeout during resolution is blocked."""
        def _mock_timeout(host, *args, **kwargs):
            raise socket.timeout("timed out")
        with patch("src.manifest_compiler.socket.getaddrinfo", side_effect=_mock_timeout):
            assert _is_safe_url("http://slow.example.com/api") is False

    def test_blocks_empty_dns_result(self):
        """Empty getaddrinfo result must fail-closed (not pass through)."""
        def _mock_empty(host, *args, **kwargs):
            return []
        with patch("src.manifest_compiler.socket.getaddrinfo", side_effect=_mock_empty):
            assert _is_safe_url("http://ghost.example.com/api") is False

    def test_blocks_ipv6_mapped_private_real(self):
        """IPv6-mapped IPv4 private addrs (::ffff:10.0.0.1) caught via ipv4_mapped check."""
        def _mock_ipv6_mapped_private(host, *args, **kwargs):
            return [(10, 1, 6, '', ('::ffff:10.0.0.1', 0, 0, 0))]
        with patch("src.manifest_compiler.socket.getaddrinfo", side_effect=_mock_ipv6_mapped_private):
            assert _is_safe_url("http://sneaky.example.com/api") is False

    def test_probe_rejects_internal_url(self):
        with patch("src.manifest_compiler.socket.getaddrinfo", side_effect=_mock_resolve_private):
            result = _verify_http_probe("http://169.254.169.254/latest/meta-data/")
            assert result["ok"] is False
            assert "blocked" in result["error"].lower()

    def test_probe_rejects_file_scheme(self):
        result = _verify_http_probe("file:///etc/passwd")
        assert result["ok"] is False
        assert "blocked" in result["error"].lower()


class TestVerifyGcpSecret:
    """GCP Secret Manager accessibility check."""

    @patch("httpx.get")
    @patch("google.auth.transport.requests.Request")
    @patch("google.auth.default")
    def test_success(self, mock_default, mock_request, mock_get):
        mock_creds = MagicMock()
        mock_creds.token = "fake-token"
        mock_default.return_value = (mock_creds, "project")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp
        result = _verify_gcp_secret("my-project", "my-secret")
        assert result["ok"] is True

    @patch("httpx.get")
    @patch("google.auth.transport.requests.Request")
    @patch("google.auth.default")
    def test_forbidden(self, mock_default, mock_request, mock_get):
        mock_creds = MagicMock()
        mock_creds.token = "fake-token"
        mock_default.return_value = (mock_creds, "project")
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_get.return_value = mock_resp
        result = _verify_gcp_secret("my-project", "my-secret")
        assert result["ok"] is False
        assert "403" in result["error"]


class TestVerifyGcpResourceExists:
    """GCP Compute resource existence check (REQ-602 expected-offline)."""

    @patch("httpx.get")
    @patch("google.auth.transport.requests.Request")
    @patch("google.auth.default")
    def test_resource_exists(self, mock_default, mock_request, mock_get):
        mock_creds = MagicMock()
        mock_creds.token = "fake-token"
        mock_default.return_value = (mock_creds, "project")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp
        result = _verify_gcp_resource_exists("proj", "us-central1-a", "my-vm")
        assert result["ok"] is True

    @patch("httpx.get")
    @patch("google.auth.transport.requests.Request")
    @patch("google.auth.default")
    def test_resource_not_found(self, mock_default, mock_request, mock_get):
        mock_creds = MagicMock()
        mock_creds.token = "fake-token"
        mock_default.return_value = (mock_creds, "project")
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_get.return_value = mock_resp
        result = _verify_gcp_resource_exists("proj", "us-central1-a", "deleted-vm")
        assert result["ok"] is False
        assert "404" in result["error"]


class TestVerifyNode:
    """Per-node verification logic."""

    def test_mandatory_with_passing_probe_and_logs(self):
        node = {
            "id": "lb-1", "type": "load_balancer",
            "monitoring": {
                "probe": {"type": "http", "url": "https://example.com"},
                "logs": [{"project": "proj", "filter": "resource.type=\"gce_instance\""}],
            },
        }
        with patch("src.manifest_compiler._verify_http_probe") as mock_probe, \
             patch("src.manifest_compiler._verify_logs_accessible") as mock_logs:
            mock_probe.return_value = {"ok": True, "latency_ms": 50, "status_code": 200, "error": None}
            mock_logs.return_value = {"ok": True, "has_data": True, "error": None}
            result = _verify_node(node)
        assert result["tier"] == "mandatory"
        assert result["status"] == "verified"

    def test_mandatory_with_failing_probe(self):
        node = {
            "id": "lb-1", "type": "load_balancer",
            "monitoring": {
                "probe": {"type": "http", "url": "https://example.com"},
                "logs": [{"project": "proj", "filter": "resource.type=\"gce_instance\""}],
            },
        }
        with patch("src.manifest_compiler._verify_http_probe") as mock_probe, \
             patch("src.manifest_compiler._verify_logs_accessible") as mock_logs:
            mock_probe.return_value = {"ok": False, "latency_ms": None, "status_code": None, "error": "timeout"}
            mock_logs.return_value = {"ok": True, "has_data": True, "error": None}
            result = _verify_node(node)
        assert result["tier"] == "mandatory"
        assert result["status"] == "failed"
        assert any("Probe failed" in e for e in result["errors"])

    def test_mandatory_blocked_when_logs_empty(self):
        """REQ-602: mandatory node blocked when logs filter valid but no entries found."""
        node = {
            "id": "lb-1", "type": "load_balancer",
            "monitoring": {
                "probe": {"type": "http", "url": "https://example.com"},
                "logs": [{"project": "proj", "filter": "resource.type=\"gce_instance\""}],
            },
        }
        with patch("src.manifest_compiler._verify_http_probe") as mock_probe, \
             patch("src.manifest_compiler._verify_logs_accessible") as mock_logs:
            mock_probe.return_value = {"ok": True, "latency_ms": 50, "status_code": 200, "error": None}
            mock_logs.return_value = {"ok": True, "has_data": False, "error": None}
            result = _verify_node(node)
        assert result["status"] == "failed"
        assert any("no log entries found" in e for e in result["errors"])

    def test_mandatory_gcp_vm_existence_check(self):
        """REQ-602: gcp_vm_status probe calls actual GCP existence check."""
        node = {
            "id": "mig-1", "type": "mig", "project_id": "proj",
            "monitoring": {"probe": {"type": "gcp_vm_status", "zone": "us-central1-a",
                                      "resource_name": "mig-1", "resource_type": "instanceGroupManagers"}},
        }
        with patch("src.manifest_compiler._verify_gcp_resource_exists") as mock_exists:
            mock_exists.return_value = {"ok": False, "error": "HTTP 404"}
            result = _verify_node(node)
        assert result["status"] == "failed"
        assert any("404" in e for e in result["errors"])
        mock_exists.assert_called_once()

    def test_mandatory_without_logs_is_blocked(self):
        """REQ-602: mandatory node blocked when no logs configured/discoverable."""
        node = {
            "id": "mig-1", "type": "mig",
            "monitoring": {"probe": {"type": "http", "url": "https://example.com"}},
        }
        with patch("src.manifest_compiler._verify_http_probe") as mock_probe:
            mock_probe.return_value = {"ok": True, "latency_ms": 50, "status_code": 200, "error": None}
            result = _verify_node(node)
        assert result["tier"] == "mandatory"
        assert result["status"] == "failed"
        assert any("No logs configured" in e for e in result["errors"])

    def test_mandatory_without_probe_is_blocked(self):
        node = {
            "id": "mig-1", "type": "mig",
            "monitoring": {"logs": [{"project": "proj", "filter": "resource.type=\"gce_instance\""}]},
        }
        with patch("src.manifest_compiler._verify_logs_accessible") as mock_logs:
            mock_logs.return_value = {"ok": True, "has_data": True, "error": None}
            result = _verify_node(node)
        assert result["tier"] == "mandatory"
        assert result["status"] == "failed"
        assert any("No probe configured" in e for e in result["errors"])

    def test_expected_offline_with_existing_resource(self):
        """REQ-602: expected-offline with existing resource = confirmed_exists."""
        node = {
            "id": "gpu-1", "type": "gpu", "expected_offline": True, "project_id": "proj",
            "monitoring": {"probe": {"type": "gcp_vm_status", "zone": "us-central1-a",
                                      "resource_name": "gpu-1"}},
        }
        with patch("src.manifest_compiler._verify_gcp_resource_exists") as mock_exists:
            mock_exists.return_value = {"ok": True, "error": None}
            result = _verify_node(node)
        assert result["tier"] == "expected_offline"
        assert result["status"] == "confirmed_exists"

    def test_expected_offline_declared_when_not_found(self):
        """REQ-602: expected-offline = declared capability, not found is OK."""
        node = {
            "id": "gpu-1", "type": "gpu", "expected_offline": True, "project_id": "proj",
            "monitoring": {"probe": {"type": "gcp_vm_status", "zone": "us-central1-a",
                                      "resource_name": "gpu-1"}},
        }
        with patch("src.manifest_compiler._verify_gcp_resource_exists") as mock_exists:
            mock_exists.return_value = {"ok": False, "error": "HTTP 404"}
            result = _verify_node(node)
        assert result["tier"] == "expected_offline"
        assert result["status"] == "declared"

    def test_expected_offline_declared_without_probe(self):
        """REQ-602: expected-offline without probe = declared (on-demand resource)."""
        node = {"id": "gpu-1", "type": "gpu", "expected_offline": True}
        result = _verify_node(node)
        assert result["tier"] == "expected_offline"
        assert result["status"] == "declared"

    def test_optional_verified(self):
        node = {
            "id": "store-1", "type": "storage",
            "monitoring": {"probe": {"type": "http", "url": "https://storage.example.com"}},
        }
        with patch("src.manifest_compiler._verify_http_probe") as mock_probe:
            mock_probe.return_value = {"ok": True, "latency_ms": 30, "status_code": 200, "error": None}
            result = _verify_node(node)
        assert result["tier"] == "optional"
        assert result["status"] == "verified"

    def test_optional_unverified(self):
        node = {"id": "cache-1", "type": "cache"}
        result = _verify_node(node)
        assert result["tier"] == "optional"
        assert result["status"] == "unverified"


class TestVerificationReport:
    """Verification report — informational, not a gate (REQ-603)."""

    def setup_method(self):
        reset_verification()

    def test_report_shows_failures(self):
        manifest = {
            "project_id": "proj", "product": "test", "environment": "prod",
            "solution": "Test", "company": "9R",
            "nodes": [
                {"id": "lb-1", "type": "load_balancer",
                 "monitoring": {"probe": {"type": "http", "url": "https://lb.example.com"}}},
            ],
            "edges": [],
        }
        with patch("src.manifest_compiler._verify_http_probe") as mock_probe:
            mock_probe.return_value = {"ok": False, "latency_ms": None, "status_code": 503, "error": "503"}
            result = compile_manifest(manifest, verify=True)
        assert result["_report_summary"]["failed"] >= 1
        assert result["_verification_report"][0]["status"] == "failed"

    def test_report_shows_all_verified(self):
        # REQ-212: compiler hydrates logs from LOG_DEFAULTS, so the LB needs only a probe;
        # logs come from the registry automatically. REQ-602 mandatory tier passes.
        manifest = {
            "project_id": "proj", "product": "pass-rpt", "environment": "prod",
            "solution": "Test", "company": "9R",
            "nodes": [
                {"id": "lb-1", "type": "load_balancer",
                 "monitoring": {"probe": {"type": "http", "url": "https://lb.example.com"}}},
            ],
            "edges": [],
        }
        with patch("src.manifest_compiler._verify_http_probe") as mock_probe, \
             patch("src.manifest_compiler._verify_logs_accessible") as mock_logs:
            mock_probe.return_value = {"ok": True, "latency_ms": 50, "status_code": 200, "error": None}
            mock_logs.return_value = {"ok": True, "has_data": True, "error": None}
            result = compile_manifest(manifest, verify=True)
        assert result["_report_summary"]["verified"] >= 1
        assert result["_report_summary"]["failed"] == 0

    def test_no_report_when_verify_false(self):
        manifest = {
            "project_id": "proj", "product": "noverify", "environment": "prod",
            "nodes": [{"id": "lb-1", "type": "load_balancer"}],
            "edges": [],
        }
        result = compile_manifest(manifest, verify=False)
        assert result["_verification_report"] == []
        assert result["_report_summary"] == {}


class TestVerificationCache:
    """Verified solutions skip re-verification (REQ-601)."""

    def setup_method(self):
        reset_verification()

    def test_cached_after_success(self):
        manifest = {
            "project_id": "proj", "product": "cached", "environment": "prod",
            "solution": "Cached", "company": "9R",
            "nodes": [
                {"id": "lb-1", "type": "load_balancer",
                 "monitoring": {"probe": {"type": "http", "url": "https://lb.example.com"}}},
            ],
            "edges": [],
        }
        with patch("src.manifest_compiler._verify_http_probe") as mock_probe, \
             patch("src.manifest_compiler._verify_logs_accessible") as mock_logs:
            mock_probe.return_value = {"ok": True, "latency_ms": 50, "status_code": 200, "error": None}
            mock_logs.return_value = {"ok": True, "has_data": True, "error": None}
            compile_manifest(manifest, verify=True)
        status = get_verification_status("cached", "Cached", "prod")
        assert status is not None
        assert "verified_at" in status

    def test_skips_verification_when_cached(self):
        manifest = {
            "project_id": "proj", "product": "cached2", "environment": "prod",
            "solution": "Cached2", "company": "9R",
            "nodes": [
                {"id": "lb-1", "type": "load_balancer",
                 "monitoring": {"probe": {"type": "http", "url": "https://lb.example.com"}}},
            ],
            "edges": [],
        }
        with patch("src.manifest_compiler._verify_http_probe") as mock_probe, \
             patch("src.manifest_compiler._verify_logs_accessible") as mock_logs:
            mock_probe.return_value = {"ok": True, "latency_ms": 50, "status_code": 200, "error": None}
            mock_logs.return_value = {"ok": True, "has_data": True, "error": None}
            # First compile — verifies
            compile_manifest(manifest, verify=True)
            call_count_1 = mock_probe.call_count
            # Second compile — should skip verification (cached)
            result2 = compile_manifest(manifest, verify=True)
            assert mock_probe.call_count == call_count_1  # no new calls
            assert result2["_verification_report"] == []  # no new report

    def test_reset_forces_reverification(self):
        manifest = {
            "project_id": "proj", "product": "reset-test", "environment": "prod",
            "solution": "Reset", "company": "9R",
            "nodes": [
                {"id": "lb-1", "type": "load_balancer",
                 "monitoring": {"probe": {"type": "http", "url": "https://lb.example.com"}}},
            ],
            "edges": [],
        }
        with patch("src.manifest_compiler._verify_http_probe") as mock_probe, \
             patch("src.manifest_compiler._verify_logs_accessible") as mock_logs:
            mock_probe.return_value = {"ok": True, "latency_ms": 50, "status_code": 200, "error": None}
            mock_logs.return_value = {"ok": True, "has_data": True, "error": None}
            compile_manifest(manifest, verify=True)
            reset_verification("reset-test", "Reset", "prod")
            assert get_verification_status("reset-test", "Reset", "prod") is None
