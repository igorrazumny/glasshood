# File: tests/test_customer_auth.py
# Purpose: Tests for customer-scoped auth (JWT + API key + RBAC)

import time
from unittest.mock import MagicMock, patch
import pytest
import jwt as pyjwt

from src.api.routes.auth import (
    _jwt_secret, _make_access_token, _make_refresh_token,
    verify_token, login, refresh, create_api_key,
    LoginRequest, RefreshRequest, ApiKeyRequest,
    _refresh_tokens, _api_keys,
)
from src.auth.rbac import require_customer


def _reset():
    _refresh_tokens.clear()
    _api_keys.clear()


def _req(token):
    req = MagicMock()
    req.headers = {"Authorization": f"Bearer {token}", "X-API-Key": ""}
    req.state = MagicMock()
    req.state.user_context = None
    return req


def _req_apikey(key):
    req = MagicMock()
    req.headers = {"Authorization": "", "X-API-Key": key}
    req.state = MagicMock()
    req.state.user_context = None
    return req


def _login():
    with patch("src.api.routes.auth.GLASSHOOD_PASSWORD", "pass"), \
         patch("src.api.routes.auth.GLASSHOOD_LOGIN", "u@test.com"):
        return login(LoginRequest(login="u@test.com", password="pass"))


class TestCustomerIdInJwt:
    def setup_method(self):
        _reset()

    def test_access_token_includes_customer_id(self):
        token = _make_access_token("u@test.com", "operator", customer_id="acme-pharma")
        payload = pyjwt.decode(token, _jwt_secret(), algorithms=["HS256"])
        assert payload["customer_id"] == "acme-pharma"

    def test_access_token_omits_empty_customer_id(self):
        token = _make_access_token("u@test.com", "admin")
        payload = pyjwt.decode(token, _jwt_secret(), algorithms=["HS256"])
        assert "customer_id" not in payload

    def test_verify_token_sets_customer_id(self):
        token = _make_access_token("u@test.com", "operator", customer_id="acme-pharma")
        req = _req(token)
        ctx = verify_token(req)
        assert ctx["customer_id"] == "acme-pharma"

    def test_verify_token_empty_customer_id(self):
        token = _make_access_token("u@test.com", "admin")
        req = _req(token)
        ctx = verify_token(req)
        assert ctx["customer_id"] == ""


class TestCustomerIdInRefresh:
    def setup_method(self):
        _reset()

    def test_refresh_preserves_customer_id(self):
        rt = _make_refresh_token("u@test.com", "operator", customer_id="acme-pharma")
        result = refresh(RefreshRequest(refresh_token=rt))
        payload = pyjwt.decode(result["token"], _jwt_secret(), algorithms=["HS256"])
        assert payload["customer_id"] == "acme-pharma"

    def test_refresh_without_customer_id(self):
        rt = _make_refresh_token("u@test.com", "admin")
        result = refresh(RefreshRequest(refresh_token=rt))
        payload = pyjwt.decode(result["token"], _jwt_secret(), algorithms=["HS256"])
        assert "customer_id" not in payload


class TestCustomerIdInApiKey:
    def setup_method(self):
        _reset()

    def test_api_key_scoped_to_customer(self):
        result = _login()
        req = _req(result["token"])
        verify_token(req)
        key = create_api_key(
            req, ApiKeyRequest(name="acme-key", role="operator", customer_id="acme-pharma"))
        api_req = _req_apikey(key["api_key"])
        ctx = verify_token(api_req)
        assert ctx["customer_id"] == "acme-pharma"

    def test_api_key_without_customer(self):
        result = _login()
        req = _req(result["token"])
        verify_token(req)
        key = create_api_key(req, ApiKeyRequest(name="global-key", role="viewer"))
        api_req = _req_apikey(key["api_key"])
        ctx = verify_token(api_req)
        assert ctx["customer_id"] == ""


class TestRequireCustomer:
    def test_super_admin_accesses_any_customer(self):
        req = MagicMock()
        req.state.user_context = {"user": "admin", "role": "admin", "customer_id": ""}
        require_customer(req, "acme-pharma")

    def test_scoped_user_accesses_own_customer(self):
        req = MagicMock()
        req.state.user_context = {"user": "u", "role": "operator", "customer_id": "acme-pharma"}
        require_customer(req, "acme-pharma")

    def test_scoped_user_denied_other_customer(self):
        req = MagicMock()
        req.state.user_context = {"user": "u", "role": "operator", "customer_id": "acme-pharma"}
        with pytest.raises(Exception):
            require_customer(req, "other-corp")

    def test_unauthenticated_denied(self):
        req = MagicMock()
        req.state.user_context = None
        with pytest.raises(Exception):
            require_customer(req, "acme-pharma")
