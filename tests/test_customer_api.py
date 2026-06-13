# File: tests/test_customer_api.py
# Purpose: Tests for customer management API endpoints

import yaml
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from src.api.routes.customers import router
from fastapi import FastAPI

# Standalone app for testing (avoids server.py startup side effects)
_app = FastAPI()
_app.include_router(router)


def _mock_auth(request):
    """Skip auth for tests."""
    request.state.user_role = "admin"


@patch("src.api.routes.customers.verify_token", side_effect=_mock_auth)
@patch("src.api.routes.customers.require_role")
@patch("src.api.routes.customers.require_customer")
class TestCustomerAPI:
    def _client(self):
        return TestClient(_app)

    def test_list_empty(self, mock_cust, mock_role, mock_auth, tmp_path):
        with patch("src.customers.manager.CUSTOMERS_DIR", str(tmp_path)):
            resp = self._client().get("/api/customers")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_create_and_list(self, mock_cust, mock_role, mock_auth, tmp_path):
        with patch("src.customers.manager.CUSTOMERS_DIR", str(tmp_path)):
            client = self._client()
            resp = client.post("/api/customers", json={
                "customer_id": "test-co",
                "display_name": "Test Company",
                "tier": "standard",
                "region": "europe-west1",
            })
            assert resp.status_code == 201
            assert resp.json()["customer_id"] == "test-co"

            resp = client.get("/api/customers")
            assert resp.json()["count"] == 1

    def test_get_customer(self, mock_cust, mock_role, mock_auth, tmp_path):
        config = {
            "customer_id": "acme-pharma",
            "display_name": "ACME",
            "tier": "professional",
            "region": "europe-west1",
        }
        (tmp_path / "acme-pharma.yaml").write_text(yaml.dump(config))
        with patch("src.customers.manager.CUSTOMERS_DIR", str(tmp_path)):
            resp = self._client().get("/api/customers/acme-pharma")
        assert resp.status_code == 200
        assert resp.json()["customer_id"] == "acme-pharma"

    def test_get_not_found(self, mock_cust, mock_role, mock_auth, tmp_path):
        with patch("src.customers.manager.CUSTOMERS_DIR", str(tmp_path)):
            resp = self._client().get("/api/customers/nonexistent")
        assert resp.status_code == 404

    def test_create_duplicate(self, mock_cust, mock_role, mock_auth, tmp_path):
        (tmp_path / "test-co.yaml").write_text("x: 1")
        with patch("src.customers.manager.CUSTOMERS_DIR", str(tmp_path)):
            resp = self._client().post("/api/customers", json={
                "customer_id": "test-co",
                "display_name": "Test",
            })
        assert resp.status_code == 400
        assert "already exists" in resp.json()["detail"]

    def test_create_invalid(self, mock_cust, mock_role, mock_auth, tmp_path):
        with patch("src.customers.manager.CUSTOMERS_DIR", str(tmp_path)):
            resp = self._client().post("/api/customers", json={
                "customer_id": "BAD",
                "display_name": "Bad",
            })
        assert resp.status_code == 400

    def test_delete_customer(self, mock_cust, mock_role, mock_auth, tmp_path):
        (tmp_path / "test-co.yaml").write_text("x: 1")
        with patch("src.customers.manager.CUSTOMERS_DIR", str(tmp_path)):
            resp = self._client().delete("/api/customers/test-co")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

    def test_delete_not_found(self, mock_cust, mock_role, mock_auth, tmp_path):
        with patch("src.customers.manager.CUSTOMERS_DIR", str(tmp_path)):
            resp = self._client().delete("/api/customers/nonexistent")
        assert resp.status_code == 404
