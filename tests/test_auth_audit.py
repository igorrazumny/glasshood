# File: tests/test_auth_audit.py
# Purpose: Tests for ALCOA+ auth audit logging

from unittest.mock import patch, MagicMock
import pytest

from src.auth.audit import log_auth_event, log_from_request, get_auth_audit_log, _auth_audit_log


def _reset_audit():
    _auth_audit_log.clear()


def _reset_auth():
    import src.api.routes.auth as mod
    mod._refresh_tokens.clear()
    mod._api_keys.clear()


class TestAlcoaFields:
    def setup_method(self):
        _reset_audit()

    def test_event_id_is_uuid(self):
        log_auth_event("login", user="u@test.com")
        entry = get_auth_audit_log()[0]
        assert len(entry["event_id"]) == 36  # UUID format
        assert entry["event_id"].count("-") == 4

    def test_event_ids_are_unique(self):
        log_auth_event("a", user="u1")
        log_auth_event("b", user="u2")
        entries = get_auth_audit_log()
        assert entries[0]["event_id"] != entries[1]["event_id"]

    def test_timestamp_is_utc_iso(self):
        log_auth_event("login", user="u@test.com")
        ts = get_auth_audit_log()[0]["timestamp"]
        assert "T" in ts
        assert ts.endswith("+00:00") or ts.endswith("Z")

    def test_all_alcoa_fields_present(self):
        log_auth_event("login", user="u", ip_address="1.2.3.4",
                       customer_id="acme", session_id="sess-1",
                       request_path="/api/auth/login", request_method="POST")
        entry = get_auth_audit_log()[0]
        for field in ["event_id", "timestamp", "action", "user", "ip_address",
                       "customer_id", "session_id", "request_path", "request_method"]:
            assert field in entry, f"Missing ALCOA+ field: {field}"

    def test_customer_id_stored(self):
        log_auth_event("login", user="u", customer_id="acme-pharma")
        assert get_auth_audit_log()[0]["customer_id"] == "acme-pharma"


class TestLogFromRequest:
    def setup_method(self):
        _reset_audit()

    def test_extracts_request_context(self):
        req = MagicMock()
        req.state.user_context = {"user": "u@test.com", "role": "admin", "customer_id": "acme"}
        req.client.host = "10.0.0.1"
        req.url.path = "/api/auth/login"
        req.method = "POST"
        log_from_request("login", req)
        entry = get_auth_audit_log()[0]
        assert entry["user"] == "u@test.com"
        assert entry["ip_address"] == "10.0.0.1"
        assert entry["customer_id"] == "acme"
        assert entry["request_path"] == "/api/auth/login"
        assert entry["request_method"] == "POST"

    def test_handles_missing_context(self):
        req = MagicMock()
        req.state.user_context = None
        req.client = None
        req.url.path = "/api/test"
        req.method = "GET"
        log_from_request("access_denied", req)
        entry = get_auth_audit_log()[0]
        assert entry["user"] == ""
        assert entry["ip_address"] == ""


class TestAuditFilters:
    def setup_method(self):
        _reset_audit()

    def test_filter_by_customer(self):
        log_auth_event("login", user="u1", customer_id="acme")
        log_auth_event("login", user="u2", customer_id="beta")
        entries = get_auth_audit_log(customer_id="acme")
        assert len(entries) == 1
        assert entries[0]["customer_id"] == "acme"

    def test_filter_by_action(self):
        log_auth_event("login", user="u1")
        log_auth_event("login_failed", user="u2")
        entries = get_auth_audit_log(action="login_failed")
        assert len(entries) == 1

    def test_limit(self):
        for i in range(10):
            log_auth_event(f"event_{i}")
        entries = get_auth_audit_log(limit=3)
        assert len(entries) == 3


class TestLogAuthEvent:
    def setup_method(self):
        _reset_audit()

    def test_logs_basic_event(self):
        log_auth_event("login", user="test@example.com")
        entries = get_auth_audit_log()
        assert len(entries) == 1
        assert entries[0]["action"] == "login"
        assert entries[0]["user"] == "test@example.com"

    def test_logs_with_details(self):
        log_auth_event("api_key_created", user="admin@test.com",
                       details={"key_id": "abc123", "role": "viewer"})
        entries = get_auth_audit_log()
        assert entries[0]["details"]["key_id"] == "abc123"

    def test_logs_ip_address(self):
        log_auth_event("login_failed", user="hacker", ip_address="192.168.1.1")
        assert get_auth_audit_log()[0]["ip_address"] == "192.168.1.1"

    def test_most_recent_first(self):
        log_auth_event("first", user="u1")
        log_auth_event("second", user="u2")
        entries = get_auth_audit_log()
        assert entries[0]["action"] == "second"

    def test_deque_maxlen(self):
        for i in range(5005):
            log_auth_event(f"event_{i}")
        entries = get_auth_audit_log(limit=10000)
        assert len(entries) == 5000


class TestLoginAudit:
    def setup_method(self):
        _reset_audit()
        _reset_auth()

    def test_successful_login_logged(self):
        from src.api.routes.auth import login as do_login, LoginRequest
        with patch("src.api.routes.auth.GLASSHOOD_PASSWORD", "pass"), \
             patch("src.api.routes.auth.GLASSHOOD_LOGIN", "u@test.com"):
            do_login(LoginRequest(login="u@test.com", password="pass"))
        login_events = [e for e in get_auth_audit_log() if e["action"] == "login"]
        assert len(login_events) == 1

    def test_failed_login_logged(self):
        from src.api.routes.auth import login as do_login, LoginRequest
        with patch("src.api.routes.auth.GLASSHOOD_PASSWORD", "pass"), \
             patch("src.api.routes.auth.GLASSHOOD_LOGIN", "u@test.com"):
            with pytest.raises(Exception):
                do_login(LoginRequest(login="u@test.com", password="wrong"))
        failed = [e for e in get_auth_audit_log() if e["action"] == "login_failed"]
        assert len(failed) == 1


class TestApiKeyAudit:
    def setup_method(self):
        _reset_audit()
        _reset_auth()

    def test_api_key_creation_logged(self):
        from src.api.routes.auth import verify_token, create_api_key, ApiKeyRequest
        from src.api.routes.auth import login as do_login, LoginRequest
        with patch("src.api.routes.auth.GLASSHOOD_PASSWORD", "pass"), \
             patch("src.api.routes.auth.GLASSHOOD_LOGIN", "admin@test.com"):
            result = do_login(LoginRequest(login="admin@test.com", password="pass"))
        req = MagicMock()
        req.headers = {"Authorization": f"Bearer {result['token']}", "X-API-Key": ""}
        req.state = MagicMock()
        req.state.user_context = None
        verify_token(req)
        create_api_key(req, ApiKeyRequest(name="test-key", role="viewer"))
        created = [e for e in get_auth_audit_log() if e["action"] == "api_key_created"]
        assert len(created) == 1
        assert created[0]["details"]["name"] == "test-key"


class TestRoleCheckAudit:
    def setup_method(self):
        _reset_audit()

    def test_role_check_failure_logged(self):
        from src.auth.rbac import require_role
        req = MagicMock()
        req.state.user_context = {"user": "viewer@test.com", "role": "viewer"}
        with pytest.raises(Exception):
            require_role(req, "admin")
        failed = [e for e in get_auth_audit_log() if e["action"] == "role_check_failed"]
        assert len(failed) == 1
        assert failed[0]["details"]["required"] == "admin"
