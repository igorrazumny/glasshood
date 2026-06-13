# File: tests/test_black_box.py
# Purpose: Tests for black box telemetry recorder

import json
import time
from unittest.mock import patch, MagicMock

import pytest


def _reset_module():
    import src.analysis.black_box as mod
    mod._last_buffer_time = 0


class TestBufferTelemetry:
    def setup_method(self):
        _reset_module()

    @patch("src.analysis.black_box.BLACKBOX_ENABLED", True)
    @patch("src.analysis.black_box.ANALYSIS_INTERVAL", 0)
    def test_writes_to_spool(self, tmp_path):
        from src.analysis.black_box import buffer_telemetry
        with patch("src.analysis.black_box.BLACKBOX_LOCAL_DIR", str(tmp_path)):
            result = buffer_telemetry(
                {"nodes": [1, 2, 3], "overall_status": "healthy"},
                {"score": 9, "summary": "OK", "stale": False},
            )
        assert result is True
        files = list(tmp_path.glob("*.json"))
        assert len(files) == 1
        data = json.loads(files[0].read_text())
        assert data["topology_summary"]["node_count"] == 3
        assert data["analysis"]["score"] == 9

    @patch("src.analysis.black_box.BLACKBOX_ENABLED", True)
    @patch("src.analysis.black_box.ANALYSIS_INTERVAL", 9999)
    def test_rate_limited(self, tmp_path):
        from src.analysis.black_box import buffer_telemetry
        import src.analysis.black_box as mod
        mod._last_buffer_time = time.time()
        with patch("src.analysis.black_box.BLACKBOX_LOCAL_DIR", str(tmp_path)):
            result = buffer_telemetry({}, {})
        assert result is False

    @patch("src.analysis.black_box.BLACKBOX_ENABLED", False)
    def test_disabled(self):
        from src.analysis.black_box import buffer_telemetry
        assert buffer_telemetry({}, {}) is False


class TestFlushToGcs:
    def setup_method(self):
        _reset_module()

    @patch("src.analysis.black_box.BLACKBOX_ENABLED", True)
    @patch("src.analysis.black_box.BLACKBOX_BUCKET", "test-bucket")
    def test_uploads_and_deletes(self, tmp_path):
        from src.analysis.black_box import flush_to_gcs
        # Create a spool file
        f = tmp_path / "test-123.json"
        f.write_text('{"test": true}')
        mock_bucket = MagicMock()
        mock_blob = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        mock_client = MagicMock()
        mock_client.bucket.return_value = mock_bucket
        with patch("src.analysis.black_box.BLACKBOX_LOCAL_DIR", str(tmp_path)), \
             patch.dict("sys.modules", {"google.cloud.storage": MagicMock()}), \
             patch("google.cloud.storage.Client", return_value=mock_client):
            count = flush_to_gcs()
        assert count == 1
        assert not f.exists()

    @patch("src.analysis.black_box.BLACKBOX_ENABLED", True)
    @patch("src.analysis.black_box.BLACKBOX_BUCKET", "")
    def test_no_bucket_skips(self):
        from src.analysis.black_box import flush_to_gcs
        assert flush_to_gcs() == 0

    @patch("src.analysis.black_box.BLACKBOX_ENABLED", True)
    @patch("src.analysis.black_box.BLACKBOX_BUCKET", "test-bucket")
    def test_gcs_failure_keeps_local(self, tmp_path):
        from src.analysis.black_box import flush_to_gcs
        f = tmp_path / "test-456.json"
        f.write_text('{"test": true}')
        with patch("src.analysis.black_box.BLACKBOX_LOCAL_DIR", str(tmp_path)):
            # Import will fail -> GCS unavailable
            count = flush_to_gcs()
        assert count == 0
        assert f.exists()


class TestPendingCount:
    @patch("src.analysis.black_box.BLACKBOX_LOCAL_DIR", "/nonexistent")
    def test_no_dir(self):
        from src.analysis.black_box import pending_count
        assert pending_count() == 0

    def test_counts_files(self, tmp_path):
        from src.analysis.black_box import pending_count
        (tmp_path / "a.json").write_text("{}")
        (tmp_path / "b.json").write_text("{}")
        with patch("src.analysis.black_box.BLACKBOX_LOCAL_DIR", str(tmp_path)):
            assert pending_count() == 2
