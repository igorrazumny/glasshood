# File: tests/test_storage_query.py
# Purpose: Tests for cross-tier query interface and storage API

from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, call

from src.storage.query import query_hot, query_warm, list_cold_archives


class TestQueryHot:
    @patch("src.storage.query.STORAGE_ENABLED", True)
    @patch("src.storage.query.STORAGE_BQ_PROJECT", "test-proj")
    @patch("src.storage.query.STORAGE_BQ_DATASET", "test_ds")
    @patch("src.storage.query.STORAGE_BQ_TABLE", "events")
    def test_queries_bigquery(self):
        mock_row = {
            "event_id": "abc",
            "timestamp": datetime(2026, 3, 9, 12, 0, tzinfo=timezone.utc),
            "source_id": "mw-01",
            "message": "test",
        }
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([mock_row])
        mock_client.query.return_value = mock_result
        with patch("google.cloud.bigquery.Client", return_value=mock_client), \
             patch("google.cloud.bigquery.QueryJobConfig"), \
             patch("google.cloud.bigquery.ScalarQueryParameter"):
            events = query_hot(limit=10, hours=24)
        assert len(events) == 1
        assert events[0]["source_id"] == "mw-01"
        mock_client.query.assert_called_once()

    @patch("src.storage.query.STORAGE_ENABLED", True)
    @patch("src.storage.query.STORAGE_BQ_PROJECT", "test-proj")
    @patch("src.storage.query.STORAGE_BQ_DATASET", "test_ds")
    @patch("src.storage.query.STORAGE_BQ_TABLE", "events")
    def test_filters_by_source_id(self):
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([])
        mock_client.query.return_value = mock_result
        with patch("google.cloud.bigquery.Client", return_value=mock_client), \
             patch("google.cloud.bigquery.QueryJobConfig"), \
             patch("google.cloud.bigquery.ScalarQueryParameter"):
            query_hot(source_id="mw-01", limit=10)
        query_str = mock_client.query.call_args[0][0]
        assert "source_id = @source_id" in query_str

    @patch("src.storage.query.STORAGE_ENABLED", True)
    @patch("src.storage.query.STORAGE_BQ_PROJECT", "test-proj")
    @patch("src.storage.query.STORAGE_BQ_DATASET", "test_ds")
    @patch("src.storage.query.STORAGE_BQ_TABLE", "events")
    def test_f004_uses_timestamp_bounds_not_date_function(self):
        """F-004: Partition filter must use timestamp bounds, not DATE()."""
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([])
        mock_client.query.return_value = mock_result
        with patch("google.cloud.bigquery.Client", return_value=mock_client), \
             patch("google.cloud.bigquery.QueryJobConfig"), \
             patch("google.cloud.bigquery.ScalarQueryParameter"):
            query_hot(limit=10, hours=24)
        query_str = mock_client.query.call_args[0][0]
        assert "DATE(" not in query_str, "Must not use DATE() — breaks partition filter"
        assert "timestamp >= @start_time" in query_str

    @patch("src.storage.query.STORAGE_ENABLED", True)
    @patch("src.storage.query.STORAGE_BQ_PROJECT", "test-proj")
    @patch("src.storage.query.STORAGE_BQ_DATASET", "test_ds")
    @patch("src.storage.query.STORAGE_BQ_TABLE", "events")
    def test_f004_end_time_uses_half_open_interval(self):
        """F-004: End time should use < (half-open), not <=."""
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([])
        mock_client.query.return_value = mock_result
        with patch("google.cloud.bigquery.Client", return_value=mock_client), \
             patch("google.cloud.bigquery.QueryJobConfig"), \
             patch("google.cloud.bigquery.ScalarQueryParameter"):
            query_warm(start_date="2026-03-01T00:00:00+00:00",
                       end_date="2026-03-07T00:00:00+00:00", limit=50)
        query_str = mock_client.query.call_args[0][0]
        assert "timestamp < @end_time" in query_str

    @patch("src.storage.query.STORAGE_ENABLED", True)
    @patch("src.storage.query.STORAGE_BQ_PROJECT", "test-proj")
    @patch("src.storage.query.STORAGE_BQ_DATASET", "test_ds")
    @patch("src.storage.query.STORAGE_BQ_TABLE", "events")
    def test_filters_by_customer_id(self):
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([])
        mock_client.query.return_value = mock_result
        with patch("google.cloud.bigquery.Client", return_value=mock_client), \
             patch("google.cloud.bigquery.QueryJobConfig"), \
             patch("google.cloud.bigquery.ScalarQueryParameter"):
            query_hot(customer_id="acme-pharma", limit=10)
        query_str = mock_client.query.call_args[0][0]
        assert "customer_id = @customer_id" in query_str

    @patch("src.storage.query.STORAGE_ENABLED", True)
    @patch("src.storage.query.STORAGE_BQ_PROJECT", "test-proj")
    @patch("src.storage.query.STORAGE_BQ_DATASET", "test_ds")
    @patch("src.storage.query.STORAGE_BQ_TABLE", "events")
    def test_no_customer_filter_when_none(self):
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([])
        mock_client.query.return_value = mock_result
        with patch("google.cloud.bigquery.Client", return_value=mock_client), \
             patch("google.cloud.bigquery.QueryJobConfig"), \
             patch("google.cloud.bigquery.ScalarQueryParameter"):
            query_hot(limit=10)
        query_str = mock_client.query.call_args[0][0]
        assert "customer_id" not in query_str

    @patch("src.storage.query.STORAGE_ENABLED", False)
    def test_disabled_returns_empty(self):
        events = query_hot()
        assert events == []


class TestQueryWarm:
    @patch("src.storage.query.STORAGE_ENABLED", True)
    @patch("src.storage.query.STORAGE_BQ_PROJECT", "test-proj")
    @patch("src.storage.query.STORAGE_BQ_DATASET", "test_ds")
    @patch("src.storage.query.STORAGE_BQ_TABLE", "events")
    def test_queries_with_date_range(self):
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([])
        mock_client.query.return_value = mock_result
        with patch("google.cloud.bigquery.Client", return_value=mock_client), \
             patch("google.cloud.bigquery.QueryJobConfig"), \
             patch("google.cloud.bigquery.ScalarQueryParameter"):
            query_warm(start_date="2026-03-01T00:00:00+00:00",
                       end_date="2026-03-07T00:00:00+00:00", limit=50)
        query_str = mock_client.query.call_args[0][0]
        assert "start_time" in query_str
        assert "end_time" in query_str

    @patch("src.storage.query.STORAGE_ENABLED", False)
    def test_disabled_returns_empty(self):
        events = query_warm()
        assert events == []


class TestListColdArchives:
    @patch("src.storage.query.get_bucket_for_customer", lambda cid: "archive-bucket")
    @patch("src.storage.query.RETENTION_ARCHIVE_BUCKET", "archive-bucket")
    def test_lists_gcs_blobs(self):
        mock_blob = MagicMock()
        mock_blob.name = "glasshood-archive/2026/03/09/batch.ndjson"
        mock_blob.size = 1024
        mock_blob.updated = datetime(2026, 3, 9, 12, 0, tzinfo=timezone.utc)

        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_bucket.list_blobs.return_value = [mock_blob]
        mock_client.bucket.return_value = mock_bucket
        with patch("google.cloud.storage.Client", return_value=mock_client):
            archives = list_cold_archives()
        assert len(archives) == 1
        assert archives[0]["name"] == "glasshood-archive/2026/03/09/batch.ndjson"
        assert archives[0]["size"] == 1024

    @patch("src.storage.query.RETENTION_ARCHIVE_BUCKET", "")
    def test_no_bucket_returns_empty(self):
        archives = list_cold_archives()
        assert archives == []

    @patch("src.storage.query.RETENTION_ARCHIVE_BUCKET", "archive-bucket")
    def test_gcs_failure_returns_empty(self):
        archives = list_cold_archives()
        assert archives == []
