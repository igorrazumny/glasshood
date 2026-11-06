# File: tests/test_coldvault_identity.py
# Purpose: REQ-GHA-025 — ColdVault metrics read with GlassHood's own short-lived identity

import asyncio
import json
import logging
from unittest.mock import MagicMock, patch

import httpx
import pytest

import src.collectors.coldvault as cv
import src.collectors.coldvault_identity as ident

TOKEN = "eyJ.fake-id-token.sig"


def _client_factory(handler):
    real = httpx.AsyncClient

    def make(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)
    return make


def _poll(handler, token=TOKEN, token_error=None):
    def fake_token():
        if token_error:
            raise token_error
        return token
    with patch.object(cv.coldvault_identity, "id_token", fake_token), \
            patch.object(cv.httpx, "AsyncClient", _client_factory(handler)):
        asyncio.run(cv.poll_once())


def _health_ok(request):
    return httpx.Response(200, json={"status": "healthy"})


@pytest.fixture(autouse=True)
def _reset():
    cv._metrics = {"system": {"ram_used_percent": 41}}  # numbers from an earlier read
    cv._metrics_status = {"read": True, "reason": "", "checked_at": 1.0}
    yield


class TestMetricsRead:
    def test_bearer_token_and_no_admin_key(self):
        seen = {}

        def handler(request):
            if request.url.path == "/api/metrics":
                seen.update(request.headers)
                return httpx.Response(200, json={"system": {"ram_used_percent": 55}})
            return _health_ok(request)
        _poll(handler)
        assert seen["authorization"] == f"Bearer {TOKEN}"
        assert "x-admin-key" not in seen
        assert cv.get_metrics() == {"system": {"ram_used_percent": 55}}
        assert cv.get_metrics_status()["read"] is True

    def test_refused_drops_old_numbers_and_says_why(self):
        def handler(request):
            if request.url.path == "/api/metrics":
                return httpx.Response(403, json={"detail": "forbidden"})
            return _health_ok(request)
        _poll(handler)
        status = cv.get_metrics_status()
        assert status["read"] is False
        assert status["reason"] == "ColdVault refused the request (HTTP 403)"
        assert status["checked_at"] > 1.0
        assert "system" not in cv.get_metrics()

    def test_token_failure_is_not_read(self):
        _poll(_health_ok, token_error=RuntimeError("sts said no"))
        status = cv.get_metrics_status()
        assert status["read"] is False
        assert status["reason"] == "identity token not obtained (RuntimeError)"
        assert "system" not in cv.get_metrics()

    def test_not_configured_is_not_read(self):
        _poll(_health_ok, token_error=ident.IdentityNotConfigured("no ColdVault metrics identity configured"))
        assert cv.get_metrics_status()["reason"] == "no ColdVault metrics identity configured"

    def test_unreadable_body_is_not_read(self):
        def handler(request):
            if request.url.path == "/api/metrics":
                return httpx.Response(200, text="<html>")
            return _health_ok(request)
        _poll(handler)
        assert cv.get_metrics_status()["read"] is False
        assert "system" not in cv.get_metrics()

    def test_token_never_logged(self, caplog):
        caplog.set_level(logging.DEBUG)

        def handler(request):
            if request.url.path == "/api/metrics":
                return httpx.Response(401)
            return _health_ok(request)
        _poll(handler)
        assert TOKEN not in caplog.text
        assert TOKEN not in json.dumps(cv.get_metrics_status())


class TestIdentityToken:
    def setup_method(self):
        ident._creds = None

    def test_exact_audience_email_and_federated_source(self, tmp_path, monkeypatch):
        cfg = tmp_path / "cred.json"
        cfg.write_text(json.dumps({
            "type": "external_account", "audience": "//iam.googleapis.com/pool",
            "service_account_impersonation_url": "https://iamcredentials.example/logs:generateAccessToken",
        }))
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(cfg))
        monkeypatch.setattr(ident, "COLDVAULT_METRICS_SA", "glasshood-coldvault@p.iam.gserviceaccount.com")
        monkeypatch.setattr(ident, "COLDVAULT_URL", "https://coldvault.ai")
        loaded = {}

        def fake_load(info, scopes=None):
            loaded.update(info)
            return MagicMock(name="federated"), None
        with patch("google.auth.load_credentials_from_dict", fake_load), \
                patch("google.auth.impersonated_credentials.Credentials") as target, \
                patch("google.auth.impersonated_credentials.IDTokenCredentials") as idt:
            ident._build()
        assert "service_account_impersonation_url" not in loaded
        assert target.call_args.kwargs["target_principal"] == "glasshood-coldvault@p.iam.gserviceaccount.com"
        assert idt.call_args.kwargs == {"target_audience": "https://coldvault.ai/api/metrics",
                                        "include_email": True}

    def test_missing_account_fails_loudly(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/nonexistent")
        monkeypatch.setattr(ident, "COLDVAULT_METRICS_SA", "")
        with pytest.raises(ident.IdentityNotConfigured):
            ident.id_token()

    def test_token_reused_until_expired(self):
        creds = MagicMock(valid=True, token="t1")
        ident._creds = creds
        assert ident.id_token() == "t1"
        creds.refresh.assert_not_called()
        creds.valid = False
        ident.id_token()
        creds.refresh.assert_called_once()
