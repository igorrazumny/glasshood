# File: tests/test_agent_transport.py
# Purpose: Tests for HTTPS batch transport with disk buffering

import json
import queue
from unittest.mock import patch, MagicMock

import httpx

from agent.transport import TransportManager


def _make_transport(tmp_path, q=None, backend_url="http://localhost:8080",
                    api_key="test-key", batch_size=10):
    return TransportManager(
        backend_url=backend_url,
        api_key=api_key,
        event_queue=q or queue.Queue(),
        buffer_dir=str(tmp_path),
        agent_id="test-agent",
        batch_size=batch_size,
    )


class TestDrainQueue:
    def test_drains_up_to_batch_size(self, tmp_path):
        q = queue.Queue()
        for i in range(5):
            q.put({"source_id": f"s{i}", "message": f"m{i}"})
        t = _make_transport(tmp_path, q, batch_size=3)
        batch = t._drain_queue()
        assert len(batch) == 3
        assert q.qsize() == 2

    def test_drains_all_if_fewer_than_batch_size(self, tmp_path):
        q = queue.Queue()
        q.put({"source_id": "s1", "message": "m1"})
        t = _make_transport(tmp_path, q, batch_size=10)
        batch = t._drain_queue()
        assert len(batch) == 1

    def test_empty_queue_returns_empty(self, tmp_path):
        t = _make_transport(tmp_path)
        assert t._drain_queue() == []


class TestBufferToDisk:
    def test_writes_json_file(self, tmp_path):
        t = _make_transport(tmp_path)
        events = [{"source_id": "x", "message": "hello"}]
        t._buffer_to_disk(events)
        files = list(tmp_path.glob("batch-*.json"))
        assert len(files) == 1
        data = json.loads(files[0].read_text())
        assert len(data) == 1
        assert data[0]["message"] == "hello"


class TestFlushBuffer:
    def test_flushes_on_200(self, tmp_path):
        t = _make_transport(tmp_path)
        # Write a buffer file
        events = [{"source_id": "x", "message": "m"}]
        t._buffer_to_disk(events)
        assert len(list(tmp_path.glob("batch-*.json"))) == 1

        # Mock successful POST
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        with patch("agent.transport.httpx.Client", return_value=mock_client):
            flushed = t._flush_buffer()

        assert flushed == 1
        assert len(list(tmp_path.glob("batch-*.json"))) == 0
        assert t._events_pushed == 1

    def test_retries_on_500(self, tmp_path):
        t = _make_transport(tmp_path)
        t._buffer_to_disk([{"source_id": "x", "message": "m"}])

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        with patch("agent.transport.httpx.Client", return_value=mock_client):
            flushed = t._flush_buffer()

        assert flushed == 0
        assert len(list(tmp_path.glob("batch-*.json"))) == 1  # file kept

    def test_keeps_file_on_connection_error(self, tmp_path):
        t = _make_transport(tmp_path)
        t._buffer_to_disk([{"source_id": "x", "message": "m"}])

        mock_client = MagicMock()
        mock_client.post.side_effect = httpx.ConnectError("refused")
        with patch("agent.transport.httpx.Client", return_value=mock_client):
            flushed = t._flush_buffer()

        assert flushed == 0
        assert len(list(tmp_path.glob("batch-*.json"))) == 1

    def test_no_files_returns_zero(self, tmp_path):
        t = _make_transport(tmp_path)
        assert t._flush_buffer() == 0

    def test_removes_corrupt_file(self, tmp_path):
        t = _make_transport(tmp_path)
        (tmp_path / "batch-123-abcd.json").write_text("not json{{{")
        t._flush_buffer()
        assert len(list(tmp_path.glob("batch-*.json"))) == 0


class TestGetStatus:
    def test_reports_pending_and_pushed(self, tmp_path):
        t = _make_transport(tmp_path)
        t._buffer_to_disk([{"source_id": "x", "message": "m"}])
        status = t.get_status()
        assert status["pending_files"] == 1
        assert status["events_pushed"] == 0
