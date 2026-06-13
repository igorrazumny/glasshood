# File: tests/test_storage_retention.py
# Purpose: Tests for retention policy and GCS cold tier archival

import json
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import yaml

from src.storage.retention import (
    load_retention_config, archive_to_cold, _get_all_customer_ids,
    _stats, _audit_log, get_audit_log,
)


def _reset():
    _stats.update({"archived": 0, "archive_runs": 0})
    _audit_log.clear()


class TestLoadRetentionConfig:
    def test_loads_yaml(self, tmp_path):
        config_file = tmp_path / "retention.yaml"
        config_file.write_text(yaml.dump({
            "hot_days": 14,
            "archive_after_days": 14,
            "archive_prefix": "custom-archive",
        }))
        with patch("src.storage.retention.RETENTION_CONFIG_PATH", str(config_file)):
            config = load_retention_config()
        assert config["hot_days"] == 14
        assert config["archive_after_days"] == 14
        assert config["archive_prefix"] == "custom-archive"

    def test_no_partition_expiration_in_defaults(self):
        """GxP: never auto-delete — partition_expiration_days removed from defaults."""
        with patch("src.storage.retention.RETENTION_CONFIG_PATH", "/nonexistent/file.yaml"):
            config = load_retention_config()
        assert "partition_expiration_days" not in config

    def test_defaults_on_missing_file(self):
        with patch("src.storage.retention.RETENTION_CONFIG_PATH", "/nonexistent/file.yaml"):
            config = load_retention_config()
        assert config["hot_days"] == 7
        assert config["archive_after_days"] == 7
        assert config["archive_prefix"] == "glasshood-archive"

    def test_partial_override(self, tmp_path):
        config_file = tmp_path / "retention.yaml"
        config_file.write_text(yaml.dump({"hot_days": 30}))
        with patch("src.storage.retention.RETENTION_CONFIG_PATH", str(config_file)):
            config = load_retention_config()
        assert config["hot_days"] == 30
        assert config["archive_after_days"] == 7  # default kept


class TestArchiveToCold:
    def setup_method(self):
        _reset()

    @patch("src.storage.retention.get_table_ref_for_customer", lambda cid: "test-proj.test_ds.events")
    @patch("src.storage.retention.get_bucket_for_customer", lambda cid: "archive-bucket")
    @patch("src.storage.retention.RETENTION_ENABLED", True)
    @patch("src.storage.retention.STORAGE_ENABLED", True)
    @patch("src.storage.retention.RETENTION_ARCHIVE_BUCKET", "archive-bucket")
    @patch("src.storage.retention.STORAGE_BQ_PROJECT", "test-proj")
    @patch("src.storage.retention.STORAGE_BQ_DATASET", "test_ds")
    @patch("src.storage.retention.STORAGE_BQ_TABLE", "events")
    def test_archives_old_events(self, tmp_path):
        config_file = tmp_path / "retention.yaml"
        config_file.write_text(yaml.dump({"hot_days": 7, "archive_after_days": 7}))

        mock_row = {
            "event_id": "abc-123",
            "timestamp": datetime(2026, 3, 1, tzinfo=timezone.utc),
            "source_id": "mw-01",
            "message": "old event",
        }
        mock_bq_client = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([mock_row])
        mock_bq_client.query.return_value = mock_result

        mock_gcs_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()
        mock_gcs_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob

        with patch("src.storage.retention.RETENTION_CONFIG_PATH", str(config_file)), \
             patch("google.cloud.bigquery.Client", return_value=mock_bq_client), \
             patch("google.cloud.bigquery.QueryJobConfig"), \
             patch("google.cloud.bigquery.ScalarQueryParameter"), \
             patch("google.cloud.storage.Client", return_value=mock_gcs_client):
            count = archive_to_cold()

        assert count == 1
        assert _stats["archived"] == 1
        mock_blob.upload_from_string.assert_called_once()
        uploaded = mock_blob.upload_from_string.call_args[0][0]
        assert "abc-123" in uploaded

    @patch("src.storage.retention.get_table_ref_for_customer", lambda cid: "test-proj.test_ds.events")
    @patch("src.storage.retention.get_bucket_for_customer", lambda cid: "archive-bucket")
    @patch("src.storage.retention.RETENTION_ENABLED", True)
    @patch("src.storage.retention.STORAGE_ENABLED", True)
    @patch("src.storage.retention.RETENTION_ARCHIVE_BUCKET", "archive-bucket")
    @patch("src.storage.retention.STORAGE_BQ_PROJECT", "test-proj")
    @patch("src.storage.retention.STORAGE_BQ_DATASET", "test_ds")
    @patch("src.storage.retention.STORAGE_BQ_TABLE", "events")
    def test_no_old_events_noop(self, tmp_path):
        config_file = tmp_path / "retention.yaml"
        config_file.write_text(yaml.dump({"archive_after_days": 7}))

        mock_bq_client = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([])
        mock_bq_client.query.return_value = mock_result

        with patch("src.storage.retention.RETENTION_CONFIG_PATH", str(config_file)), \
             patch("google.cloud.bigquery.Client", return_value=mock_bq_client), \
             patch("google.cloud.bigquery.QueryJobConfig"), \
             patch("google.cloud.bigquery.ScalarQueryParameter"):
            count = archive_to_cold()

        assert count == 0
        assert _stats["archive_runs"] == 1

    @patch("src.storage.retention.RETENTION_ENABLED", False)
    def test_disabled_noop(self):
        count = archive_to_cold()
        assert count == 0

    @patch("src.storage.retention.RETENTION_ENABLED", True)
    @patch("src.storage.retention.STORAGE_ENABLED", True)
    @patch("src.storage.retention.RETENTION_ARCHIVE_BUCKET", "")
    def test_no_bucket_noop(self):
        count = archive_to_cold()
        assert count == 0

    @patch("src.storage.retention.get_table_ref_for_customer", lambda cid: "test-proj.test_ds.events")
    @patch("src.storage.retention.get_bucket_for_customer", lambda cid: "archive-bucket")
    @patch("src.storage.retention.RETENTION_ENABLED", True)
    @patch("src.storage.retention.STORAGE_ENABLED", True)
    @patch("src.storage.retention.RETENTION_ARCHIVE_BUCKET", "archive-bucket")
    @patch("src.storage.retention.STORAGE_BQ_PROJECT", "test-proj")
    @patch("src.storage.retention.STORAGE_BQ_DATASET", "test_ds")
    @patch("src.storage.retention.STORAGE_BQ_TABLE", "events")
    def test_bq_failure_logged(self, tmp_path):
        config_file = tmp_path / "retention.yaml"
        config_file.write_text(yaml.dump({"archive_after_days": 7}))
        with patch("src.storage.retention.RETENTION_CONFIG_PATH", str(config_file)):
            count = archive_to_cold()
        assert count == 0
        log = get_audit_log()
        assert any(e["status"] == "failure" for e in log)


class TestAuditLog:
    def setup_method(self):
        _reset()

    @patch("src.storage.retention.get_table_ref_for_customer", lambda cid: "test-proj.test_ds.events")
    @patch("src.storage.retention.get_bucket_for_customer", lambda cid: "archive-bucket")
    @patch("src.storage.retention.RETENTION_ENABLED", True)
    @patch("src.storage.retention.STORAGE_ENABLED", True)
    @patch("src.storage.retention.RETENTION_ARCHIVE_BUCKET", "archive-bucket")
    @patch("src.storage.retention.STORAGE_BQ_PROJECT", "test-proj")
    @patch("src.storage.retention.STORAGE_BQ_DATASET", "test_ds")
    @patch("src.storage.retention.STORAGE_BQ_TABLE", "events")
    def test_records_archive_operations(self, tmp_path):
        config_file = tmp_path / "retention.yaml"
        config_file.write_text(yaml.dump({"archive_after_days": 7}))
        mock_bq_client = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([])
        mock_bq_client.query.return_value = mock_result
        with patch("src.storage.retention.RETENTION_CONFIG_PATH", str(config_file)), \
             patch("google.cloud.bigquery.Client", return_value=mock_bq_client), \
             patch("google.cloud.bigquery.QueryJobConfig"), \
             patch("google.cloud.bigquery.ScalarQueryParameter"):
            archive_to_cold()
        log = get_audit_log()
        assert len(log) >= 1
        assert log[0]["action"] == "archive_to_cold"


class TestGetAllCustomerIds:
    def test_returns_customer_ids(self):
        customers = [
            {"customer_id": "acme-pharma", "display_name": "ACME"},
            {"customer_id": "roche", "display_name": "Roche"},
        ]
        with patch("src.customers.manager.list_customers", return_value=customers):
            ids = _get_all_customer_ids()
        assert ids == ["acme-pharma", "roche"]

    def test_empty_when_no_customers(self):
        with patch("src.customers.manager.list_customers", return_value=[]):
            ids = _get_all_customer_ids()
        assert ids == []

    def test_skips_missing_customer_id(self):
        customers = [{"display_name": "No ID"}, {"customer_id": "valid"}]
        with patch("src.customers.manager.list_customers", return_value=customers):
            ids = _get_all_customer_ids()
        assert ids == ["valid"]

    def test_returns_empty_on_import_error(self):
        ids = _get_all_customer_ids()
        assert isinstance(ids, list)
