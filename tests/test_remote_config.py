# File: tests/test_remote_config.py
# Purpose: Tests for remote config push manager

import json
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from agent.remote_config import RemoteConfigManager


class TestRemoteConfigManager(unittest.TestCase):
    """Remote config fetch, cache, and callback behavior."""

    def _make_manager(self, config_dir=None):
        d = config_dir or tempfile.mkdtemp()
        return RemoteConfigManager(
            backend_url="http://localhost:8080",
            api_key="test-key",
            agent_id="agent-01",
            config_dir=d,
        )

    def test_config_hash_deterministic(self):
        mgr = self._make_manager()
        h1 = mgr._config_hash({"a": 1, "b": 2})
        h2 = mgr._config_hash({"b": 2, "a": 1})
        self.assertEqual(h1, h2)  # sorted keys

    def test_config_hash_different_for_different_config(self):
        mgr = self._make_manager()
        h1 = mgr._config_hash({"a": 1})
        h2 = mgr._config_hash({"a": 2})
        self.assertNotEqual(h1, h2)

    @patch("agent.remote_config.httpx.get")
    def test_fetch_success(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"whitelist": {"allowed_sources": ["sap-*"]}},
        )
        mgr = self._make_manager()
        config = mgr._fetch_remote_config()
        self.assertIsNotNone(config)
        self.assertIn("whitelist", config)

    @patch("agent.remote_config.httpx.get")
    def test_fetch_404_returns_none(self, mock_get):
        mock_get.return_value = MagicMock(status_code=404)
        mgr = self._make_manager()
        self.assertIsNone(mgr._fetch_remote_config())

    @patch("agent.remote_config.httpx.get")
    def test_fetch_connection_error(self, mock_get):
        import httpx
        mock_get.side_effect = httpx.ConnectError("refused")
        mgr = self._make_manager()
        self.assertIsNone(mgr._fetch_remote_config())
        self.assertEqual(mgr._last_error, "Connection refused")

    def test_save_and_load_cache(self):
        with tempfile.TemporaryDirectory() as d:
            mgr = self._make_manager(d)
            config = {"collectors": [{"type": "file_tail"}]}
            mgr._save_cached_config(config)
            loaded = mgr.load_cached_config()
            self.assertEqual(loaded, config)

    def test_load_cache_missing_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            mgr = self._make_manager(d)
            self.assertIsNone(mgr.load_cached_config())

    def test_apply_config_calls_callbacks(self):
        mgr = self._make_manager()
        received = []
        mgr.on_update(lambda c: received.append(c))
        mgr._apply_config({"setting": "value"})
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["setting"], "value")

    def test_apply_same_config_no_duplicate_callback(self):
        mgr = self._make_manager()
        received = []
        mgr.on_update(lambda c: received.append(c))
        mgr._apply_config({"x": 1})
        mgr._apply_config({"x": 1})  # same config
        self.assertEqual(len(received), 1)  # only called once

    @patch("agent.remote_config.httpx.get")
    def test_poll_once_updates(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"new_setting": True},
        )
        with tempfile.TemporaryDirectory() as d:
            mgr = self._make_manager(d)
            received = []
            mgr.on_update(lambda c: received.append(c))
            updated = mgr.poll_once()
            self.assertTrue(updated)
            self.assertEqual(len(received), 1)

    @patch("agent.remote_config.httpx.get")
    def test_poll_once_no_change(self, mock_get):
        config = {"x": 1}
        mock_get.return_value = MagicMock(
            status_code=200, json=lambda: config,
        )
        mgr = self._make_manager()
        mgr.poll_once()  # first poll
        updated = mgr.poll_once()  # same config
        self.assertFalse(updated)

    def test_get_status(self):
        mgr = self._make_manager()
        status = mgr.get_status()
        self.assertIn("current_hash", status)
        self.assertIn("last_error", status)

    def test_stop(self):
        mgr = self._make_manager()
        mgr.stop()
        self.assertTrue(mgr._stop.is_set())
