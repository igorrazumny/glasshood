# File: tests/test_customer_isolation.py
# Purpose: Tests for customer isolation in API endpoints

from unittest.mock import MagicMock, patch
import pytest

from src.api.routes.auth import (
    _make_access_token, verify_token, _refresh_tokens, _api_keys,
)


def _reset():
    _refresh_tokens.clear()
    _api_keys.clear()


def _req(token):
    req = MagicMock()
    req.headers = {"Authorization": f"Bearer {token}", "X-API-Key": ""}
    req.state = MagicMock()
    req.state.user_context = None
    return req


class TestIngestIsolation:
    def setup_method(self):
        _reset()

    def test_scoped_user_overrides_customer_id(self):
        from src.api.routes.ingest import ingest_events, IngestBatch
        token = _make_access_token("u@acme.com", "operator", customer_id="acme")
        req = _req(token)
        with patch("src.api.routes.ingest.processor") as mock_proc:
            mock_proc.process_batch.return_value = {"processed": 1}
            body = IngestBatch(agent_id="agent-1", customer_id="wrong-corp",
                               events=[{"msg": "test"}])
            ingest_events(req, body)
        # Body's customer_id should have been overridden to "acme"
        call_args = mock_proc.process_batch.call_args
        event = call_args[0][0][0]
        assert event["customer_id"] == "acme"

    def test_superadmin_uses_body_customer_id(self):
        from src.api.routes.ingest import ingest_events, IngestBatch
        token = _make_access_token("admin@9r.ai", "admin")
        req = _req(token)
        with patch("src.api.routes.ingest.processor") as mock_proc:
            mock_proc.process_batch.return_value = {"processed": 1}
            body = IngestBatch(agent_id="agent-1", customer_id="acme",
                               events=[{"msg": "test"}])
            ingest_events(req, body)
        event = mock_proc.process_batch.call_args[0][0][0]
        assert event["customer_id"] == "acme"


class TestStorageIsolation:
    def setup_method(self):
        _reset()

    def test_scoped_user_forced_to_own_customer(self):
        from src.api.routes.storage import storage_events
        token = _make_access_token("u@acme.com", "operator", customer_id="acme")
        req = _req(token)
        with patch("src.api.routes.storage.query") as mock_q:
            mock_q.query_hot.return_value = []
            storage_events(req, customer_id="other-corp")
        # Should have been forced to "acme"
        call_kwargs = mock_q.query_hot.call_args[1]
        assert call_kwargs["customer_id"] == "acme"

    def test_scoped_user_archives_forced(self):
        from src.api.routes.storage import storage_archives
        token = _make_access_token("u@acme.com", "operator", customer_id="acme")
        req = _req(token)
        with patch("src.api.routes.storage.query") as mock_q:
            mock_q.list_cold_archives.return_value = []
            storage_archives(req, customer_id="other-corp")
        call_kwargs = mock_q.list_cold_archives.call_args[1]
        assert call_kwargs["customer_id"] == "acme"


class TestCustomerApiIsolation:
    def setup_method(self):
        _reset()

    def test_scoped_admin_lists_own_customer_only(self):
        from src.api.routes.customers import list_customers
        token = _make_access_token("admin@acme.com", "admin", customer_id="acme")
        req = _req(token)
        with patch("src.api.routes.customers.manager") as mock_mgr:
            mock_mgr.list_customers.return_value = [
                {"customer_id": "acme"}, {"customer_id": "beta"}
            ]
            result = list_customers(req)
        assert result["count"] == 1
        assert result["customers"][0]["customer_id"] == "acme"

    def test_scoped_admin_denied_other_customer_detail(self):
        from src.api.routes.customers import get_customer
        token = _make_access_token("admin@acme.com", "admin", customer_id="acme")
        req = _req(token)
        with pytest.raises(Exception):  # 403
            get_customer(req, "other-corp")

    def test_superadmin_accesses_any_customer(self):
        from src.api.routes.customers import get_customer
        token = _make_access_token("super@9r.ai", "admin")
        req = _req(token)
        with patch("src.api.routes.customers.manager") as mock_mgr:
            mock_mgr.get_customer.return_value = {"customer_id": "acme"}
            result = get_customer(req, "acme")
        assert result["customer_id"] == "acme"
