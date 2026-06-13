# File: tests/test_jwt_session.py
# Purpose: Tests for JWT session management (Annex 11 §10.2 idle timeout)

import time
from unittest.mock import MagicMock, patch
import pytest
import jwt as pyjwt

from src.api.routes.auth import (
    _jwt_secret, _make_access_token, _make_refresh_token,
    verify_token, login, refresh,
    LoginRequest, RefreshRequest, _refresh_tokens, _api_keys,
)


def _reset():
    _refresh_tokens.clear()
    _api_keys.clear()


def _login_result():
    with patch("src.api.routes.auth.GLASSHOOD_PASSWORD", "pass"), \
         patch("src.api.routes.auth.GLASSHOOD_LOGIN", "u@test.com"):
        return login(LoginRequest(login="u@test.com", password="pass"))


def _req_with_token(token):
    req = MagicMock()
    req.headers = {"Authorization": f"Bearer {token}", "X-API-Key": ""}
    req.state = MagicMock()
    req.state.user_context = None
    return req


class TestAccessToken:
    def setup_method(self):
        _reset()

    def test_contains_expected_claims(self):
        token = _make_access_token("u@test.com", "admin")
        payload = pyjwt.decode(token, _jwt_secret(), algorithms=["HS256"])
        assert payload["sub"] == "u@test.com"
        assert payload["role"] == "admin"
        assert payload["type"] == "access"
        assert "exp" in payload
        assert "jti" in payload

    def test_expires_in_15_minutes(self):
        token = _make_access_token("u@test.com", "admin")
        payload = pyjwt.decode(token, _jwt_secret(), algorithms=["HS256"])
        ttl = payload["exp"] - payload["iat"]
        assert ttl == 900

    def test_verifiable(self):
        token = _make_access_token("u@test.com", "viewer")
        req = _req_with_token(token)
        ctx = verify_token(req)
        assert ctx["user"] == "u@test.com"
        assert ctx["role"] == "viewer"


class TestRefreshToken:
    def setup_method(self):
        _reset()

    def test_contains_expected_claims(self):
        token = _make_refresh_token("u@test.com", "admin")
        payload = pyjwt.decode(token, _jwt_secret(), algorithms=["HS256"])
        assert payload["type"] == "refresh"
        assert payload["sub"] == "u@test.com"

    def test_24h_ttl(self):
        token = _make_refresh_token("u@test.com", "admin")
        payload = pyjwt.decode(token, _jwt_secret(), algorithms=["HS256"])
        ttl = payload["exp"] - payload["iat"]
        assert ttl == 86400

    def test_stored_server_side(self):
        token = _make_refresh_token("u@test.com", "admin")
        payload = pyjwt.decode(token, _jwt_secret(), algorithms=["HS256"])
        assert payload["jti"] in _refresh_tokens

    def test_cannot_be_used_as_access(self):
        token = _make_refresh_token("u@test.com", "admin")
        req = _req_with_token(token)
        with pytest.raises(Exception):
            verify_token(req)


class TestRefreshEndpoint:
    def setup_method(self):
        _reset()

    def test_returns_new_access_token(self):
        result = _login_result()
        new = refresh(RefreshRequest(refresh_token=result["refresh_token"]))
        assert "token" in new
        assert new["expires_in"] == 900
        req = _req_with_token(new["token"])
        ctx = verify_token(req)
        assert ctx["user"] == "u@test.com"

    def test_expired_refresh_rejected(self):
        expired = pyjwt.encode(
            {"sub": "u@test.com", "role": "admin", "type": "refresh",
             "exp": int(time.time()) - 10, "jti": "old"},
            _jwt_secret(), algorithm="HS256",
        )
        with pytest.raises(Exception):
            refresh(RefreshRequest(refresh_token=expired))

    def test_revoked_refresh_rejected(self):
        result = _login_result()
        rt = result["refresh_token"]
        payload = pyjwt.decode(rt, _jwt_secret(), algorithms=["HS256"])
        del _refresh_tokens[payload["jti"]]
        with pytest.raises(Exception):
            refresh(RefreshRequest(refresh_token=rt))

    def test_access_token_as_refresh_rejected(self):
        result = _login_result()
        with pytest.raises(Exception):
            refresh(RefreshRequest(refresh_token=result["token"]))


class TestIdleTimeout:
    def setup_method(self):
        _reset()

    def test_idle_timeout_via_access_expiry(self):
        with patch("src.api.routes.auth.JWT_ACCESS_TTL", 1):
            result = _login_result()
        time.sleep(1.5)
        req = _req_with_token(result["token"])
        with pytest.raises(Exception):
            verify_token(req)

    def test_refresh_extends_session(self):
        result = _login_result()
        new = refresh(RefreshRequest(refresh_token=result["refresh_token"]))
        req = _req_with_token(new["token"])
        ctx = verify_token(req)
        assert ctx["user"] == "u@test.com"
