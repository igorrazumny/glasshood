# File: tests/test_session_mgmt.py
# Purpose: Tests for session management (logout, /me, active sessions)

from unittest.mock import MagicMock, patch
import pytest
import jwt as pyjwt

from src.api.routes.auth import (
    _jwt_secret, verify_token, login, logout, get_me, list_sessions, refresh,
    LoginRequest, RefreshRequest, _refresh_tokens, _api_keys,
)


def _reset():
    _refresh_tokens.clear()
    _api_keys.clear()


def _login():
    with patch("src.api.routes.auth.GLASSHOOD_PASSWORD", "pass"), \
         patch("src.api.routes.auth.GLASSHOOD_LOGIN", "u@test.com"):
        return login(LoginRequest(login="u@test.com", password="pass"))


def _req(token):
    req = MagicMock()
    req.headers = {"Authorization": f"Bearer {token}", "X-API-Key": ""}
    req.state = MagicMock()
    req.state.user_context = None
    return req


class TestGetMe:
    def setup_method(self):
        _reset()

    def test_returns_user_context(self):
        result = _login()
        req = _req(result["token"])
        me = get_me(req)
        assert me["user"] == "u@test.com"
        assert me["role"] == "admin"
        assert me["customer_id"] == ""


class TestLogout:
    def setup_method(self):
        _reset()

    def test_revokes_refresh_token(self):
        result = _login()
        rt = result["refresh_token"]
        payload = pyjwt.decode(rt, _jwt_secret(), algorithms=["HS256"])
        assert payload["jti"] in _refresh_tokens

        req = _req(result["token"])
        verify_token(req)
        logout(req, RefreshRequest(refresh_token=rt))
        assert payload["jti"] not in _refresh_tokens

    def test_refresh_fails_after_logout(self):
        result = _login()
        req = _req(result["token"])
        verify_token(req)
        logout(req, RefreshRequest(refresh_token=result["refresh_token"]))
        with pytest.raises(Exception):
            refresh(RefreshRequest(refresh_token=result["refresh_token"]))

    def test_logout_idempotent(self):
        result = _login()
        req = _req(result["token"])
        verify_token(req)
        logout(req, RefreshRequest(refresh_token=result["refresh_token"]))
        verify_token(req)
        r = logout(req, RefreshRequest(refresh_token=result["refresh_token"]))
        assert r["status"] == "logged_out"


class TestListSessions:
    def setup_method(self):
        _reset()

    def test_lists_active_sessions(self):
        result = _login()
        req = _req(result["token"])
        verify_token(req)
        sessions = list_sessions(req)
        assert sessions["count"] >= 1
        assert any(s["user"] == "u@test.com" for s in sessions["sessions"])

    def test_session_has_expected_fields(self):
        result = _login()
        req = _req(result["token"])
        verify_token(req)
        sessions = list_sessions(req)
        s = sessions["sessions"][0]
        assert "user" in s
        assert "role" in s
        assert "customer_id" in s
        assert "expires_at" in s

    def test_customer_scoped_admin_sees_own_only(self):
        from src.api.routes.auth import _make_access_token, _make_refresh_token
        _make_refresh_token("acme-user", "admin", customer_id="acme")
        _make_refresh_token("beta-user", "operator", customer_id="beta")
        token = _make_access_token("acme-admin", "admin", customer_id="acme")
        req = _req(token)
        verify_token(req)
        sessions = list_sessions(req)
        for s in sessions["sessions"]:
            assert s["customer_id"] == "acme"
        assert sessions["count"] == 1

    def test_super_admin_sees_all(self):
        from src.api.routes.auth import _make_access_token, _make_refresh_token
        _make_refresh_token("acme-user", "operator", customer_id="acme")
        _make_refresh_token("beta-user", "operator", customer_id="beta")
        token = _make_access_token("superadmin", "admin")
        req = _req(token)
        verify_token(req)
        sessions = list_sessions(req)
        assert sessions["count"] >= 2
