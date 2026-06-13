# File: tests/test_auth_rbac.py
# Purpose: Tests for RBAC system, API key auth, and role enforcement

import time
from unittest.mock import MagicMock, patch
import pytest

import jwt as pyjwt

from src.auth.rbac import require_role, get_role_level, ROLE_HIERARCHY


def _reset_auth():
    import src.api.routes.auth as mod
    mod._refresh_tokens.clear()
    mod._api_keys.clear()


def _login(email="admin@example.com", password="testpass"):
    from src.api.routes.auth import login as do_login, LoginRequest
    with patch("src.api.routes.auth.GLASSHOOD_PASSWORD", password), \
         patch("src.api.routes.auth.GLASSHOOD_LOGIN", email):
        return do_login(LoginRequest(login=email, password=password))


def _mock_request_with_token(token):
    req = MagicMock()
    req.headers = {"Authorization": f"Bearer {token}"}
    req.state = MagicMock()
    req.state.user_context = None
    return req


def _mock_request_with_api_key(key):
    req = MagicMock()
    req.headers = {"Authorization": "", "X-API-Key": key}
    req.state = MagicMock()
    req.state.user_context = None
    return req


class TestRoleHierarchy:
    def test_admin_is_highest(self):
        assert get_role_level("admin") > get_role_level("operator")
        assert get_role_level("operator") > get_role_level("viewer")

    def test_unknown_role_is_zero(self):
        assert get_role_level("unknown") == 0

    def test_all_roles_defined(self):
        assert set(ROLE_HIERARCHY.keys()) == {"admin", "operator", "viewer"}


class TestLogin:
    def setup_method(self):
        _reset_auth()

    def test_login_returns_token_with_role(self):
        result = _login()
        assert "token" in result
        assert result["role"] == "admin"

    def test_login_returns_refresh_token(self):
        result = _login()
        assert "refresh_token" in result

    def test_login_returns_access_ttl(self):
        result = _login()
        assert result["expires_in"] == 900  # 15 min access token


class TestVerifyToken:
    def setup_method(self):
        _reset_auth()

    def test_returns_user_context(self):
        from src.api.routes.auth import verify_token
        result = _login()
        req = _mock_request_with_token(result["token"])
        ctx = verify_token(req)
        assert ctx["user"] == "admin@example.com"
        assert ctx["role"] == "admin"

    def test_sets_request_state(self):
        from src.api.routes.auth import verify_token
        result = _login()
        req = _mock_request_with_token(result["token"])
        verify_token(req)
        assert req.state.user_context["role"] == "admin"

    def test_expired_token_rejected(self):
        from src.api.routes.auth import verify_token, _jwt_secret
        expired_token = pyjwt.encode(
            {"sub": "test@test.com", "role": "admin", "type": "access",
             "exp": int(time.time()) - 10, "jti": "test"},
            _jwt_secret(), algorithm="HS256",
        )
        req = _mock_request_with_token(expired_token)
        with pytest.raises(Exception):
            verify_token(req)

    def test_refresh_token_rejected_as_access(self):
        from src.api.routes.auth import verify_token, _jwt_secret
        token = pyjwt.encode(
            {"sub": "test@test.com", "role": "admin", "type": "refresh",
             "exp": int(time.time()) + 3600, "jti": "test"},
            _jwt_secret(), algorithm="HS256",
        )
        req = _mock_request_with_token(token)
        with pytest.raises(Exception):
            verify_token(req)

    def test_missing_auth_rejected(self):
        from src.api.routes.auth import verify_token
        req = MagicMock()
        req.headers = {"Authorization": "", "X-API-Key": ""}
        with pytest.raises(Exception):
            verify_token(req)


class TestApiKeyAuth:
    def setup_method(self):
        _reset_auth()

    def test_create_and_use_api_key(self):
        from src.api.routes.auth import verify_token, create_api_key, ApiKeyRequest
        result = _login()
        req = _mock_request_with_token(result["token"])
        verify_token(req)
        key_result = create_api_key(req, ApiKeyRequest(name="test-key", role="viewer"))
        assert "api_key" in key_result
        assert key_result["role"] == "viewer"
        api_req = _mock_request_with_api_key(key_result["api_key"])
        ctx = verify_token(api_req)
        assert ctx["role"] == "viewer"
        assert "apikey:test-key" in ctx["user"]

    def test_invalid_api_key_rejected(self):
        from src.api.routes.auth import verify_token
        req = _mock_request_with_api_key("invalid-key-12345")
        with pytest.raises(Exception):
            verify_token(req)

    def test_list_api_keys_masks_key(self):
        from src.api.routes.auth import verify_token, create_api_key, list_api_keys, ApiKeyRequest
        result = _login()
        req = _mock_request_with_token(result["token"])
        verify_token(req)
        create_api_key(req, ApiKeyRequest(name="my-key", role="operator"))
        verify_token(req)
        keys_result = list_api_keys(req)
        assert keys_result["count"] == 1
        assert "api_key" not in keys_result["api_keys"][0]
        assert keys_result["api_keys"][0]["name"] == "my-key"

    def test_revoke_api_key(self):
        from src.api.routes.auth import verify_token, create_api_key, revoke_api_key, ApiKeyRequest
        result = _login()
        req = _mock_request_with_token(result["token"])
        verify_token(req)
        key_result = create_api_key(req, ApiKeyRequest(name="revoke-me", role="viewer"))
        verify_token(req)
        revoke_result = revoke_api_key(req, key_result["key_id"])
        assert revoke_result["status"] == "revoked"
        api_req = _mock_request_with_api_key(key_result["api_key"])
        with pytest.raises(Exception):
            verify_token(api_req)


class TestRequireRole:
    def test_admin_passes_all_checks(self):
        req = MagicMock()
        req.state.user_context = {"user": "admin@test.com", "role": "admin"}
        require_role(req, "viewer")
        require_role(req, "operator")
        require_role(req, "admin")

    def test_viewer_fails_operator_check(self):
        req = MagicMock()
        req.state.user_context = {"user": "viewer@test.com", "role": "viewer"}
        with pytest.raises(Exception):
            require_role(req, "operator")

    def test_operator_fails_admin_check(self):
        req = MagicMock()
        req.state.user_context = {"user": "op@test.com", "role": "operator"}
        with pytest.raises(Exception):
            require_role(req, "admin")

    def test_no_context_raises_401(self):
        req = MagicMock()
        req.state.user_context = None
        with pytest.raises(Exception):
            require_role(req, "viewer")
