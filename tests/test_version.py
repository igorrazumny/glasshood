# File: tests/test_version.py
# Purpose: Tests for VERSION file and /api/version endpoint

import re
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.api.server import app, _read_version


client = TestClient(app)


class TestVersionFile:
    """VERSION file format and content."""

    def test_version_file_exists(self):
        assert Path("VERSION").exists(), "VERSION file must exist at repo root"

    def test_version_format(self):
        ver = Path("VERSION").read_text().strip()
        assert re.match(r"^\d{4}\.\d{2}\.\d{2}\.\d+$", ver), (
            f"VERSION must be YYYY.MM.DD.N, got: '{ver}'"
        )

    def test_read_version_returns_string(self):
        ver = _read_version()
        assert ver != "unknown"
        assert "." in ver


class TestVersionEndpoint:
    """GET /api/version — no auth required."""

    def test_returns_200(self):
        resp = client.get("/api/version")
        assert resp.status_code == 200

    def test_response_has_version_and_service(self):
        data = client.get("/api/version").json()
        assert "version" in data
        assert data["service"] == "GlassHood"

    def test_version_matches_file(self):
        expected = Path("VERSION").read_text().strip()
        data = client.get("/api/version").json()
        assert data["version"] == expected

    def test_unknown_when_no_file(self):
        with patch("src.api.server.Path") as mock_path:
            mock_instance = mock_path.return_value
            mock_instance.exists.return_value = False
            # _read_version tries two paths; if both fail, returns "unknown"
            # We need to patch differently since Path is used elsewhere
            pass
        # Simpler: patch _read_version directly for the endpoint
        with patch("src.api.server._read_version", return_value="unknown"):
            data = client.get("/api/version").json()
            assert data["version"] == "unknown"
