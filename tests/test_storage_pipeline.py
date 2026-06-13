# File: tests/test_storage_pipeline.py
# Purpose: Tests for BigQuery streaming insert pipeline

import json
from unittest.mock import patch, MagicMock

from src.storage.pipeline import (
    buffer_events, flush_to_bigquery, ensure_table, flush_loop, stop,
    _buffer, _stats, _audit_log, _flush_lock,
)


def _reset():
    _buffer.clear()
    _stats.update({"buffered": 0, "flushed_bq": 0, "failed": 0})
    _audit_log.clear()
    # Reset singleton guard for tests
    import src.storage.pipeline as _pipeline
    _pipeline._flush_started = False
    _pipeline._stop.clear()


class TestBufferEvents:
    def setup_method(self):
        _reset()

    @patch("src.storage.pipeline.STORAGE_ENABLED", True)
    def test_buffers_events(self):
        events = [
            {"source_id": "mw-01", "message": "test1"},
            {"source_id": "mw-02", "message": "test2"},
        ]
        count = buffer_events(events)
        assert count == 2
        assert len(_buffer) == 2
        assert _stats["buffered"] == 2

    @patch("src.storage.pipeline.STORAGE_ENABLED", False)
    def test_disabled_noop(self):
        count = buffer_events([{"source_id": "x", "message": "m"}])
        assert count == 0
        assert len(_buffer) == 0

    @patch("src.storage.pipeline.STORAGE_ENABLED", True)
    def test_adds_event_id_and_ingested_at(self):
        buffer_events([{"source_id": "s1", "message": "m1"}])
        row = _buffer[0]
        assert "event_id" in row
        assert len(row["event_id"]) == 36  # UUID format
        assert "ingested_at" in row
        assert row["source_id"] == "s1"

    @patch("src.storage.pipeline.STORAGE_ENABLED", True)
    def test_serializes_tags(self):
        buffer_events([{"source_id": "s", "message": "m", "tags": {"env": "prod"}}])
        row = _buffer[0]
        assert json.loads(row["tags"]) == {"env": "prod"}

    @patch("src.storage.pipeline.STORAGE_ENABLED", True)
    def test_defaults_for_missing_fields(self):
        buffer_events([{"source_id": "s", "message": "m"}])
        row = _buffer[0]
        assert row["severity"] == "info"
        assert row["source_type"] == ""
        assert row["customer_id"] == ""
        assert row["tags"] == "{}"

    @patch("src.storage.pipeline.STORAGE_ENABLED", True)
    def test_preserves_customer_id(self):
        buffer_events([{"source_id": "s", "message": "m", "customer_id": "acme-pharma"}])
        row = _buffer[0]
        assert row["customer_id"] == "acme-pharma"


class TestFlushToBigquery:
    def setup_method(self):
        _reset()

    @patch("src.storage.pipeline.STORAGE_ENABLED", True)
    @patch("src.storage.pipeline.STORAGE_BQ_PROJECT", "test-proj")
    @patch("src.storage.pipeline.STORAGE_BQ_DATASET", "test_ds")
    @patch("src.storage.pipeline.STORAGE_BQ_TABLE", "events")
    def test_inserts_to_bigquery(self, tmp_path):
        buffer_events([{"source_id": "s1", "message": "m1"}])
        mock_client = MagicMock()
        mock_client.insert_rows_json.return_value = []
        with patch("src.storage.pipeline.STORAGE_LOCAL_DIR", str(tmp_path)), \
             patch("google.cloud.bigquery.Client", return_value=mock_client):
            count = flush_to_bigquery()
        assert count == 1
        mock_client.insert_rows_json.assert_called_once()
        assert _stats["flushed_bq"] == 1

    @patch("src.storage.pipeline.STORAGE_ENABLED", True)
    @patch("src.storage.pipeline.STORAGE_BQ_PROJECT", "test-proj")
    @patch("src.storage.pipeline.STORAGE_BQ_DATASET", "test_ds")
    @patch("src.storage.pipeline.STORAGE_BQ_TABLE", "events")
    def test_bq_failure_spools_local(self, tmp_path):
        buffer_events([{"source_id": "s1", "message": "m1"}])
        with patch("src.storage.pipeline.STORAGE_LOCAL_DIR", str(tmp_path)):
            count = flush_to_bigquery()
        assert count == 0
        assert _stats["failed"] == 1
        spool_files = list(tmp_path.glob("batch-*.json"))
        assert len(spool_files) == 1

    @patch("src.storage.pipeline.STORAGE_ENABLED", True)
    @patch("src.storage.pipeline.STORAGE_BQ_PROJECT", "test-proj")
    def test_empty_buffer_noop(self, tmp_path):
        with patch("src.storage.pipeline.STORAGE_LOCAL_DIR", str(tmp_path)):
            count = flush_to_bigquery()
        assert count == 0

    @patch("src.storage.pipeline.STORAGE_ENABLED", True)
    @patch("src.storage.pipeline.STORAGE_BQ_PROJECT", "test-proj")
    @patch("src.storage.pipeline.STORAGE_BQ_DATASET", "test_ds")
    @patch("src.storage.pipeline.STORAGE_BQ_TABLE", "events")
    def test_f005_passes_row_ids_for_idempotency(self, tmp_path):
        """F-005: insert_rows_json must receive row_ids for deduplication."""
        buffer_events([{"source_id": "s1", "message": "m1"}])
        mock_client = MagicMock()
        mock_client.insert_rows_json.return_value = []
        with patch("src.storage.pipeline.STORAGE_LOCAL_DIR", str(tmp_path)), \
             patch("google.cloud.bigquery.Client", return_value=mock_client):
            flush_to_bigquery()
        call_kwargs = mock_client.insert_rows_json.call_args
        assert call_kwargs[1].get("row_ids") is not None or len(call_kwargs[0]) >= 3

    @patch("src.storage.pipeline.STORAGE_ENABLED", True)
    @patch("src.storage.pipeline.STORAGE_BQ_PROJECT", "test-proj")
    @patch("src.storage.pipeline.STORAGE_BQ_DATASET", "test_ds")
    @patch("src.storage.pipeline.STORAGE_BQ_TABLE", "events")
    def test_f005_partial_failure_spools_only_failed_rows(self, tmp_path):
        """F-005: Only failed rows should be re-spooled, not the whole batch."""
        buffer_events([
            {"source_id": "s1", "message": "m1"},
            {"source_id": "s2", "message": "m2"},
            {"source_id": "s3", "message": "m3"},
        ])
        mock_client = MagicMock()
        # Only row at index 1 fails
        mock_client.insert_rows_json.return_value = [{"index": 1, "errors": ["bad"]}]
        with patch("src.storage.pipeline.STORAGE_LOCAL_DIR", str(tmp_path)), \
             patch("google.cloud.bigquery.Client", return_value=mock_client):
            count = flush_to_bigquery()
        assert count == 2  # 3 total - 1 failed = 2 succeeded
        assert _stats["flushed_bq"] == 2
        assert _stats["failed"] == 1
        spool_files = list(tmp_path.glob("batch-*.json"))
        assert len(spool_files) == 1
        spooled = json.loads(spool_files[0].read_text())
        assert len(spooled) == 1  # Only the failed row

    @patch("src.storage.pipeline.STORAGE_ENABLED", True)
    @patch("src.storage.pipeline.STORAGE_BQ_PROJECT", "")
    def test_f008_missing_bq_project_does_not_spool(self, tmp_path):
        """F-008: Missing BQ config must not spool to disk."""
        buffer_events([{"source_id": "s1", "message": "m1"}])
        with patch("src.storage.pipeline.STORAGE_LOCAL_DIR", str(tmp_path)):
            count = flush_to_bigquery()
        assert count == 0
        spool_files = list(tmp_path.glob("batch-*.json"))
        assert len(spool_files) == 0, "Must not spool when BQ is not configured"

    @patch("src.storage.pipeline.STORAGE_ENABLED", False)
    def test_disabled_noop(self):
        count = flush_to_bigquery()
        assert count == 0


class TestEnsureTable:
    @patch("src.storage.pipeline.STORAGE_ENABLED", True)
    @patch("src.storage.pipeline.STORAGE_BQ_PROJECT", "test-proj")
    @patch("src.storage.pipeline.STORAGE_BQ_DATASET", "test_ds")
    @patch("src.storage.pipeline.STORAGE_BQ_TABLE", "events")
    def test_creates_dataset_and_table(self):
        mock_client = MagicMock()
        mock_client.get_dataset.side_effect = Exception("not found")
        mock_client.get_table.side_effect = Exception("not found")
        with patch("google.cloud.bigquery.Client", return_value=mock_client), \
             patch("google.cloud.bigquery.DatasetReference") as mock_ds_ref, \
             patch("google.cloud.bigquery.Dataset"), \
             patch("google.cloud.bigquery.Table"), \
             patch("google.cloud.bigquery.SchemaField"), \
             patch("google.cloud.bigquery.TimePartitioning"):
            result = ensure_table()
        assert result is True
        mock_client.create_dataset.assert_called_once()
        mock_client.create_table.assert_called_once()

    @patch("src.storage.pipeline.STORAGE_ENABLED", True)
    @patch("src.storage.pipeline.STORAGE_BQ_PROJECT", "test-proj")
    @patch("src.storage.pipeline.STORAGE_BQ_DATASET", "test_ds")
    @patch("src.storage.pipeline.STORAGE_BQ_TABLE", "events")
    def test_idempotent_existing(self):
        mock_client = MagicMock()
        with patch("google.cloud.bigquery.Client", return_value=mock_client), \
             patch("google.cloud.bigquery.DatasetReference"):
            result = ensure_table()
        assert result is True
        mock_client.create_dataset.assert_not_called()
        mock_client.create_table.assert_not_called()

    @patch("src.storage.pipeline.STORAGE_ENABLED", False)
    def test_disabled_noop(self):
        assert ensure_table() is False


class TestFlushLoopSingleton:
    """F-007: flush_loop must be singleton — no duplicate threads."""
    def setup_method(self):
        _reset()

    @patch("src.storage.pipeline.STORAGE_ENABLED", True)
    @patch("src.storage.pipeline.STORAGE_FLUSH_INTERVAL", 1)
    def test_f007_second_call_is_noop(self):
        """F-007: Second flush_loop call returns immediately (singleton)."""
        import src.storage.pipeline as _pipeline
        _pipeline._flush_started = True  # Simulate already running
        # Should return immediately without entering the while loop
        flush_loop(interval=1)
        # If we got here, it didn't block — singleton guard worked

    @patch("src.storage.pipeline.STORAGE_ENABLED", True)
    def test_f007_stop_resets_singleton(self):
        """F-007: stop() resets the singleton so flush_loop can restart."""
        import src.storage.pipeline as _pipeline
        _pipeline._flush_started = True
        stop()
        assert _pipeline._flush_started is False


class TestAuditLog:
    def setup_method(self):
        _reset()

    @patch("src.storage.pipeline.STORAGE_ENABLED", True)
    @patch("src.storage.pipeline.STORAGE_BQ_PROJECT", "test-proj")
    @patch("src.storage.pipeline.STORAGE_BQ_DATASET", "test_ds")
    @patch("src.storage.pipeline.STORAGE_BQ_TABLE", "events")
    def test_records_flush_operations(self, tmp_path):
        buffer_events([{"source_id": "s1", "message": "m1"}])
        mock_client = MagicMock()
        mock_client.insert_rows_json.return_value = []
        with patch("src.storage.pipeline.STORAGE_LOCAL_DIR", str(tmp_path)), \
             patch("google.cloud.bigquery.Client", return_value=mock_client):
            flush_to_bigquery()
        from src.storage.pipeline import get_audit_log
        log = get_audit_log()
        assert len(log) == 1
        assert log[0]["action"] == "flush_bq"
        assert log[0]["status"] == "success"
