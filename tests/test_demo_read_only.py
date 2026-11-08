# File: tests/test_demo_read_only.py
# Purpose: REQ-GHA-043 — the Live demo role can change nothing, on any route that exists now or later

from unittest.mock import patch

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from src.api.server import _OPEN_WRITES, app

WRITES = ("POST", "PUT", "PATCH", "DELETE")


def _write_routes():
    out = []
    for r in app.routes:
        if isinstance(r, APIRoute) and r.path not in _OPEN_WRITES:
            out += [(m, r.path) for m in r.methods if m in WRITES]
    return sorted(out)


def _as(role, user="someone"):
    return {"user": user, "role": role, "customer_id": ""}


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


def test_there_are_write_routes_to_check():
    paths = {p for _, p in _write_routes()}
    assert {"/api/discovery/trigger", "/api/manifests/verify", "/api/ingest/heartbeat",
            "/api/security/findings/{cve_id}/status", "/api/integrations/snow/sync"} <= paths


@pytest.mark.parametrize("method,path", _write_routes())
def test_the_demo_role_is_refused_the_same_way_everywhere(client, method, path):
    def viewer(request):
        request.state.user_context = _as("viewer")
        return request.state.user_context
    with patch("src.api.routes.auth.verify_token", side_effect=viewer):
        r = client.request(method, path.replace("{", "").replace("}", ""), json={}, headers={"Authorization": "Bearer t"})
    assert r.status_code == 403, f"{method} {path}: {r.status_code}"


@pytest.mark.parametrize("method,path", _write_routes())
def test_nobody_signed_out_can_write(client, method, path):
    r = client.request(method, path.replace("{", "").replace("}", ""), json={})
    assert r.status_code in (401, 403), f"{method} {path}: {r.status_code}"


def test_the_open_list_is_only_sign_in_out_and_the_crash_report():
    assert _OPEN_WRITES == {"/api/auth/login", "/api/auth/refresh", "/api/auth/logout", "/api/frontend-error"}


def test_an_audit_name_is_the_signed_in_user(client):
    def operator(request):
        request.state.user_context = _as("operator", "real@example.com")
        return request.state.user_context
    with patch("src.api.routes.auth.verify_token", side_effect=operator), \
         patch("src.api.routes.security.verify_token", side_effect=operator), \
         patch("src.api.routes.security.update_finding_status", return_value=True) as update:
        r = client.post("/api/security/findings/CVE-1/status", json={"status": "accepted", "user": "forged@example.com"})
    assert r.status_code == 200
    update.assert_called_once_with("CVE-1", "accepted", "real@example.com")
