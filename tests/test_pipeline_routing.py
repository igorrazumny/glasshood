# File: tests/test_pipeline_routing.py
# Purpose: Tests for per-customer routing in storage pipeline

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.storage import pipeline


class TestFlushPerCustomerRouting(unittest.TestCase):
    def setUp(self):
        pipeline._buffer.clear()
        pipeline._stats.update({"buffered": 0, "flushed_bq": 0, "failed": 0})
        pipeline._audit_log.clear()

    @patch("src.storage.pipeline.STORAGE_BQ_PROJECT", "proj")
    @patch("src.storage.pipeline.STORAGE_ENABLED", True)
    @patch("src.storage.pipeline.get_table_ref_for_customer")
    @patch("src.storage.pipeline.group_events_by_customer")
    def test_routes_to_per_customer_table(self, mock_group, mock_tref):
        acme_rows = [{"event_id": "1", "customer_id": "acme"}]
        roche_rows = [{"event_id": "2", "customer_id": "roche"}]
        mock_group.return_value = {"acme": acme_rows, "roche": roche_rows}
        mock_tref.side_effect = lambda cid: f"proj.glasshood_{cid}.events"

        mock_client = MagicMock()
        mock_client.insert_rows_json.return_value = []
        with patch("google.cloud.bigquery.Client", return_value=mock_client):
            pipeline._buffer.extend(acme_rows + roche_rows)
            flushed = pipeline.flush_to_bigquery()

        self.assertEqual(flushed, 2)
        calls = mock_client.insert_rows_json.call_args_list
        self.assertEqual(len(calls), 2)
        tables_used = {c[0][0] for c in calls}
        self.assertIn("proj.glasshood_acme.events", tables_used)
        self.assertIn("proj.glasshood_roche.events", tables_used)

    @patch("src.storage.pipeline.STORAGE_BQ_PROJECT", "proj")
    @patch("src.storage.pipeline.STORAGE_ENABLED", True)
    @patch("src.storage.pipeline.get_table_ref_for_customer")
    @patch("src.storage.pipeline.group_events_by_customer")
    @patch("src.storage.pipeline._spool_to_disk")
    def test_partial_failure_spools_failed_group(self, mock_spool, mock_group, mock_tref):
        ok_rows = [{"event_id": "1", "customer_id": "ok"}]
        fail_rows = [{"event_id": "2", "customer_id": "fail"}]
        mock_group.return_value = {"ok": ok_rows, "fail": fail_rows}
        mock_tref.side_effect = lambda cid: f"proj.glasshood_{cid}.events"

        mock_client = MagicMock()
        mock_client.insert_rows_json.side_effect = [
            [],  # ok group succeeds
            Exception("BQ down"),  # fail group raises
        ]
        with patch("google.cloud.bigquery.Client", return_value=mock_client):
            pipeline._buffer.extend(ok_rows + fail_rows)
            flushed = pipeline.flush_to_bigquery()

        self.assertEqual(flushed, 1)
        mock_spool.assert_called_once_with(fail_rows)


class TestRetrySpoolPerCustomer(unittest.TestCase):
    @patch("src.storage.pipeline.STORAGE_BQ_PROJECT", "proj")
    @patch("src.storage.pipeline.get_table_ref_for_customer")
    def test_retry_routes_by_customer(self, mock_tref):
        mock_tref.side_effect = lambda cid: f"proj.glasshood_{cid or 'shared'}.events"
        with tempfile.TemporaryDirectory() as d:
            rows = [
                {"event_id": "1", "customer_id": "acme"},
                {"event_id": "2", "customer_id": ""},
            ]
            spool_file = Path(d) / "batch-1234-abcd.json"
            spool_file.write_text(json.dumps(rows))

            mock_client = MagicMock()
            mock_client.insert_rows_json.return_value = []
            with patch("src.storage.pipeline.STORAGE_LOCAL_DIR", d):
                with patch("google.cloud.bigquery.Client", return_value=mock_client):
                    pipeline._stats.update({"flushed_bq": 0})
                    pipeline._audit_log.clear()
                    flushed = pipeline._retry_spool()

            self.assertEqual(flushed, 2)
            self.assertFalse(spool_file.exists())
            calls = mock_client.insert_rows_json.call_args_list
            self.assertEqual(len(calls), 2)


class TestEnsureTablePerCustomer(unittest.TestCase):
    @patch("src.storage.pipeline.STORAGE_BQ_PROJECT", "proj")
    @patch("src.storage.pipeline.STORAGE_ENABLED", True)
    @patch("src.storage.pipeline.get_dataset_for_customer")
    def test_customer_dataset_created(self, mock_ds):
        mock_ds.return_value = "glasshood_acme_pharma"
        mock_client = MagicMock()
        mock_client.get_dataset.side_effect = Exception("not found")
        mock_client.get_table.side_effect = Exception("not found")
        with patch("google.cloud.bigquery.Client", return_value=mock_client):
            with patch("google.cloud.bigquery.DatasetReference") as mock_dsref:
                with patch("google.cloud.bigquery.Dataset"):
                    with patch("google.cloud.bigquery.Table"):
                        with patch("google.cloud.bigquery.SchemaField"):
                            with patch("google.cloud.bigquery.TimePartitioning"):
                                result = pipeline.ensure_table(customer_id="acme-pharma")
        mock_ds.assert_called_once_with("acme-pharma")
        self.assertTrue(result)
