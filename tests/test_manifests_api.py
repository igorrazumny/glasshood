# File: tests/test_manifests_api.py
# Purpose: Tests for /api/manifests endpoint and verification endpoints

from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient


class TestLoadManifests:
    def test_loads_platform_prod_manifest(self):
        """Platform prod manifest loads and has expected structure."""
        from src.api.routes.manifests import _load_manifests
        manifests = _load_manifests()
        assert len(manifests) >= 1
        platform = [m for m in manifests
                    if m.get("product") == "platform" and m.get("environment") == "prod"]
        assert len(platform) == 1
        p = platform[0]
        assert "Platform" in p["display_name"]
        assert len(p["groups"]) >= 1

    def test_manifest_groups_have_required_fields(self):
        """Each group has name, label, style, order, and nodes list."""
        from src.api.routes.manifests import _load_manifests
        manifests = _load_manifests()
        for manifest in manifests:
            for group in manifest.get("groups", []):
                assert "name" in group, f"Missing name in group"
                assert "label" in group, f"Missing label in group {group.get('name')}"
                assert "style" in group, f"Missing style in group {group.get('name')}"
                assert isinstance(group.get("nodes", []), list)

    def test_manifest_nodes_have_id(self):
        """Each node in manifest nodes[] list has an id."""
        from src.api.routes.manifests import _load_manifests
        manifests = _load_manifests()
        for manifest in manifests:
            for node in manifest.get("nodes", []):
                assert "id" in node, f"Missing id in node: {node}"

    def test_row_col_grid_fields_present(self):
        """Groups in schema v1 manifests have row/col placement fields."""
        from src.api.routes.manifests import _load_manifests
        manifests = _load_manifests()
        for m in manifests:
            if m.get("schema_version", 0) >= 1:
                for group in m.get("groups", []):
                    assert "row" in group, f"Missing row in {m['product']}/{group['name']}"
                    assert "col" in group, f"Missing col in {m['product']}/{group['name']}"

    def test_platform_has_connections(self):
        """Platform manifest has connections (edges or connects_to on nodes)."""
        from src.api.routes.manifests import _load_manifests
        manifests = _load_manifests()
        platform = [m for m in manifests
                    if m.get("product") == "platform" and m.get("environment") == "prod"]
        assert len(platform) == 1
        # Connections come from connects_to/receives_from on nodes (REQ-702)
        nodes = platform[0].get("nodes", [])
        has_connects = any(n.get("connects_to") or n.get("children_template") for n in nodes)
        has_edges = len(platform[0].get("edges", [])) > 0
        assert has_connects or has_edges

    def test_empty_dir_returns_empty(self):
        """Returns empty list when manifest dir doesn't exist."""
        from src.api.routes.manifests import _load_manifests
        with patch("src.api.routes.manifests.MANIFEST_DIR") as mock_dir:
            mock_dir.exists.return_value = False
            assert _load_manifests() == []


class TestVerifyEndpoint:
    """Tests for POST /api/manifests/verify (REQ-601)."""

    def _get_client(self):
        from src.api.server import app
        return TestClient(app)

    def test_verify_requires_auth(self):
        client = self._get_client()
        resp = client.post("/api/manifests/verify")
        assert resp.status_code in (401, 403)

    @patch("src.api.routes.manifests.verify_token")
    @patch("src.manifest_compiler._verify_http_probe")
    @patch("src.manifest_compiler._verify_logs_accessible")
    def test_verify_returns_structure(self, mock_logs, mock_probe, mock_auth):
        mock_auth.return_value = None
        mock_probe.return_value = {"ok": True, "latency_ms": 50, "status_code": 200, "error": None}
        mock_logs.return_value = {"ok": True, "has_data": True, "error": None}
        from src.manifest_compiler import reset_verification
        reset_verification()
        client = self._get_client()
        resp = client.post("/api/manifests/verify")
        assert resp.status_code == 200
        data = resp.json()
        assert "manifests" in data
        assert "reports" in data


class TestResetVerificationEndpoint:
    """Tests for POST /api/manifests/reset-verification."""

    def _get_client(self):
        from src.api.server import app
        return TestClient(app)

    def test_reset_requires_auth(self):
        client = self._get_client()
        resp = client.post("/api/manifests/reset-verification")
        assert resp.status_code in (401, 403)

    @patch("src.api.routes.manifests.verify_token")
    def test_reset_returns_scope(self, mock_auth):
        mock_auth.return_value = None
        client = self._get_client()
        resp = client.post("/api/manifests/reset-verification")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "reset"
        assert "scope" in data

    @patch("src.api.routes.manifests.verify_token")
    def test_reset_scoped(self, mock_auth):
        mock_auth.return_value = None
        client = self._get_client()
        resp = client.post("/api/manifests/reset-verification?product=test&solution=Test&environment=prod")
        assert resp.status_code == 200
        assert "test" in resp.json()["scope"]
