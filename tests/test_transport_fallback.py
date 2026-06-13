# File: tests/test_transport_fallback.py
# Purpose: Tests for gRPC→HTTPS fallback in transport manager

import queue
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from agent.transport import TransportManager


class TestTransportModeConfig(unittest.TestCase):
    """Transport manager mode selection."""

    def test_https_mode_no_grpc(self):
        eq = queue.Queue()
        t = TransportManager("http://localhost:8080", "key", eq, "/tmp/test",
                             "agent-1", transport_mode="https")
        self.assertIsNone(t._grpc)

    def test_grpc_mode_creates_client(self):
        eq = queue.Queue()
        t = TransportManager("https://glasshood.example.com", "key", eq, "/tmp/test",
                             "agent-1", transport_mode="grpc")
        self.assertIsNotNone(t._grpc)
        t._grpc.close()

    def test_grpc_tls_from_https_url(self):
        eq = queue.Queue()
        t = TransportManager("https://example.com", "key", eq, "/tmp/test",
                             "agent-1", transport_mode="grpc")
        self.assertTrue(t._grpc._use_tls)
        t._grpc.close()

    def test_grpc_no_tls_from_http_url(self):
        eq = queue.Queue()
        t = TransportManager("http://localhost:8080", "key", eq, "/tmp/test",
                             "agent-1", transport_mode="grpc")
        self.assertFalse(t._grpc._use_tls)
        t._grpc.close()

    def test_status_includes_filtered_count(self):
        eq = queue.Queue()
        with tempfile.TemporaryDirectory() as d:
            t = TransportManager("http://localhost:8080", "key", eq, d, "agent-1")
            status = t.get_status()
            self.assertIn("events_filtered", status)


class TestFallbackBehavior(unittest.TestCase):
    """gRPC → HTTPS fallback."""

    def test_grpc_success_skips_https(self):
        eq = queue.Queue()
        with tempfile.TemporaryDirectory() as d:
            t = TransportManager("http://localhost:8080", "key", eq, d,
                                 "agent-1", transport_mode="grpc")
            t._grpc = MagicMock()
            t._grpc.push_events.return_value = (True, "ok")
            with patch.object(t, "_push_https") as mock_https:
                t._buffer_to_disk([{"msg": "test"}])
                flushed = t._flush_buffer()
                self.assertEqual(flushed, 1)
                mock_https.assert_not_called()

    def test_https_fallback_on_grpc_failure(self):
        eq = queue.Queue()
        with tempfile.TemporaryDirectory() as d:
            t = TransportManager("http://localhost:8080", "key", eq, d,
                                 "agent-1", transport_mode="grpc")
            t._grpc = MagicMock()
            t._grpc.push_events.return_value = (False, "unavailable")
            with patch.object(t, "_push_https", return_value=True) as mock_https:
                t._buffer_to_disk([{"msg": "test"}])
                flushed = t._flush_buffer()
                self.assertEqual(flushed, 1)
                mock_https.assert_called_once()

    def test_https_only_no_grpc_attempt(self):
        eq = queue.Queue()
        with tempfile.TemporaryDirectory() as d:
            t = TransportManager("http://localhost:8080", "key", eq, d,
                                 "agent-1", transport_mode="https")
            with patch.object(t, "_push_https", return_value=True) as mock_https:
                t._buffer_to_disk([{"msg": "test"}])
                flushed = t._flush_buffer()
                self.assertEqual(flushed, 1)
                mock_https.assert_called_once()

    def test_both_fail_retries_later(self):
        eq = queue.Queue()
        with tempfile.TemporaryDirectory() as d:
            t = TransportManager("http://localhost:8080", "key", eq, d,
                                 "agent-1", transport_mode="grpc")
            t._grpc = MagicMock()
            t._grpc.push_events.return_value = (False, "down")
            with patch.object(t, "_push_https", return_value=None):
                t._buffer_to_disk([{"msg": "test"}])
                flushed = t._flush_buffer()
                self.assertEqual(flushed, 0)
                # Buffer file still exists for retry
                self.assertEqual(t.get_status()["pending_files"], 1)
