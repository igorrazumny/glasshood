# File: tests/test_customer_manager.py
# Purpose: Tests for customer config management

import yaml
from unittest.mock import patch

from src.customers.manager import (
    validate_customer_id, validate_config, list_customers,
    get_customer, create_customer, delete_customer,
)


def _valid_config(**overrides):
    base = {
        "customer_id": "acme-pharma",
        "display_name": "ACME Pharmaceuticals",
        "tier": "professional",
        "region": "europe-west1",
    }
    base.update(overrides)
    return base


class TestValidateCustomerId:
    def test_valid_ids(self):
        assert validate_customer_id("acme-pharma") is True
        assert validate_customer_id("roche-basel-01") is True
        assert validate_customer_id("abc") is True

    def test_too_short(self):
        assert validate_customer_id("ab") is False

    def test_uppercase_rejected(self):
        assert validate_customer_id("Acme-Pharma") is False

    def test_leading_hyphen(self):
        assert validate_customer_id("-acme") is False

    def test_trailing_hyphen(self):
        assert validate_customer_id("acme-") is False

    def test_special_chars(self):
        assert validate_customer_id("acme_pharma") is False
        assert validate_customer_id("acme pharma") is False


class TestValidateConfig:
    def test_valid(self):
        assert validate_config(_valid_config()) == []

    def test_missing_required(self):
        errors = validate_config({"customer_id": "test"})
        assert any("display_name" in e for e in errors)

    def test_invalid_tier(self):
        errors = validate_config(_valid_config(tier="premium"))
        assert any("tier" in e for e in errors)

    def test_invalid_customer_id(self):
        errors = validate_config(_valid_config(customer_id="BAD"))
        assert any("customer_id" in e for e in errors)


class TestListCustomers:
    def test_lists_yaml_files(self, tmp_path):
        (tmp_path / "acme.yaml").write_text(yaml.dump(_valid_config()))
        (tmp_path / "roche.yaml").write_text(yaml.dump(
            _valid_config(customer_id="roche-01")))
        (tmp_path / "_example.yaml").write_text("# skip me")
        with patch("src.customers.manager.CUSTOMERS_DIR", str(tmp_path)):
            result = list_customers()
        assert len(result) == 2
        ids = {c["customer_id"] for c in result}
        assert "acme-pharma" in ids

    def test_empty_dir(self, tmp_path):
        with patch("src.customers.manager.CUSTOMERS_DIR", str(tmp_path)):
            assert list_customers() == []

    def test_nonexistent_dir(self, tmp_path):
        with patch("src.customers.manager.CUSTOMERS_DIR", str(tmp_path / "nope")):
            assert list_customers() == []


class TestGetCustomer:
    def test_found(self, tmp_path):
        cfg = _valid_config()
        (tmp_path / "acme-pharma.yaml").write_text(yaml.dump(cfg))
        with patch("src.customers.manager.CUSTOMERS_DIR", str(tmp_path)):
            result = get_customer("acme-pharma")
        assert result["customer_id"] == "acme-pharma"

    def test_not_found(self, tmp_path):
        with patch("src.customers.manager.CUSTOMERS_DIR", str(tmp_path)):
            assert get_customer("nonexistent") is None

    def test_invalid_id_returns_none(self):
        assert get_customer("BAD ID") is None


class TestCreateCustomer:
    def test_creates_file(self, tmp_path):
        with patch("src.customers.manager.CUSTOMERS_DIR", str(tmp_path)):
            result = create_customer(_valid_config())
        assert result["customer_id"] == "acme-pharma"
        assert (tmp_path / "acme-pharma.yaml").exists()
        # Check defaults applied
        assert result["bigquery_dataset"] == "glasshood_acme_pharma"
        assert result["gcs_archive_bucket"] == "glasshood-archive-acme-pharma"

    def test_rejects_duplicate(self, tmp_path):
        (tmp_path / "acme-pharma.yaml").write_text("existing: true")
        with patch("src.customers.manager.CUSTOMERS_DIR", str(tmp_path)):
            try:
                create_customer(_valid_config())
                assert False, "Should have raised ValueError"
            except ValueError as e:
                assert "already exists" in str(e)

    def test_rejects_invalid(self, tmp_path):
        with patch("src.customers.manager.CUSTOMERS_DIR", str(tmp_path)):
            try:
                create_customer({"customer_id": "x"})
                assert False, "Should have raised ValueError"
            except ValueError as e:
                assert "Invalid config" in str(e)


class TestDeleteCustomer:
    def test_deletes(self, tmp_path):
        (tmp_path / "acme-pharma.yaml").write_text("x: 1")
        with patch("src.customers.manager.CUSTOMERS_DIR", str(tmp_path)):
            assert delete_customer("acme-pharma") is True
        assert not (tmp_path / "acme-pharma.yaml").exists()

    def test_not_found(self, tmp_path):
        with patch("src.customers.manager.CUSTOMERS_DIR", str(tmp_path)):
            assert delete_customer("nonexistent") is False

    def test_invalid_id(self):
        assert delete_customer("BAD") is False
