# File: tests/test_whitelist.py
# Purpose: Tests for customer-configurable data whitelist

import unittest

from agent.whitelist import (
    WhitelistConfig, load_whitelist, filter_event, filter_batch,
    REDACT_PLACEHOLDER,
)


class TestLoadWhitelist(unittest.TestCase):
    """Loading whitelist config from dict."""

    def test_empty_dict_returns_defaults(self):
        wl = load_whitelist({})
        self.assertEqual(wl.allowed_sources, [])
        self.assertEqual(wl.blocked_patterns, [])
        self.assertFalse(wl.drop_on_block)

    def test_none_returns_defaults(self):
        wl = load_whitelist(None)
        self.assertEqual(wl.allowed_sources, [])

    def test_loads_all_fields(self):
        wl = load_whitelist({
            "allowed_sources": ["sap-*"],
            "allowed_fields": ["message", "severity"],
            "blocked_patterns": ["password=\\S+"],
            "drop_on_block": True,
        })
        self.assertEqual(wl.allowed_sources, ["sap-*"])
        self.assertEqual(wl.allowed_fields, ["message", "severity"])
        self.assertEqual(wl.blocked_patterns, ["password=\\S+"])
        self.assertTrue(wl.drop_on_block)


class TestSourceFilter(unittest.TestCase):
    """Whitelist source filtering with fnmatch patterns."""

    def test_no_filter_passes_all(self):
        config = WhitelistConfig()
        event = {"source_id": "anything", "message": "hello"}
        self.assertIsNotNone(filter_event(event, config))

    def test_allowed_source_passes(self):
        config = WhitelistConfig(allowed_sources=["sap-*"])
        event = {"source_id": "sap-erp-01", "message": "data"}
        self.assertIsNotNone(filter_event(event, config))

    def test_disallowed_source_dropped(self):
        config = WhitelistConfig(allowed_sources=["sap-*"])
        event = {"source_id": "unknown-system", "message": "data"}
        self.assertIsNone(filter_event(event, config))

    def test_multiple_patterns(self):
        config = WhitelistConfig(allowed_sources=["sap-*", "mes-*"])
        self.assertIsNotNone(filter_event({"source_id": "mes-01"}, config))
        self.assertIsNone(filter_event({"source_id": "scada-01"}, config))

    def test_empty_source_id_dropped_when_filtered(self):
        config = WhitelistConfig(allowed_sources=["sap-*"])
        self.assertIsNone(filter_event({"source_id": ""}, config))


class TestBlockedPatterns(unittest.TestCase):
    """Regex-based content redaction."""

    def test_redacts_matched_text(self):
        config = WhitelistConfig(blocked_patterns=[r"password=\S+"])
        event = {"source_id": "sap", "message": "login password=secret123 ok"}
        result = filter_event(event, config)
        self.assertIsNotNone(result)
        self.assertNotIn("secret123", result["message"])
        self.assertIn(REDACT_PLACEHOLDER, result["message"])

    def test_drop_on_block_true(self):
        config = WhitelistConfig(blocked_patterns=[r"password=\S+"], drop_on_block=True)
        event = {"source_id": "sap", "message": "login password=secret123"}
        self.assertIsNone(filter_event(event, config))

    def test_no_match_passes_through(self):
        config = WhitelistConfig(blocked_patterns=[r"password=\S+"])
        event = {"source_id": "sap", "message": "normal log line"}
        result = filter_event(event, config)
        self.assertEqual(result["message"], "normal log line")

    def test_multiple_patterns(self):
        config = WhitelistConfig(blocked_patterns=[r"password=\S+", r"Bearer\s+\S+"])
        event = {"message": "auth password=x Bearer tok123 done"}
        result = filter_event(event, config)
        self.assertNotIn("password=x", result["message"])
        self.assertNotIn("tok123", result["message"])

    def test_invalid_regex_skipped(self):
        config = WhitelistConfig(blocked_patterns=[r"[invalid", r"password=\S+"])
        event = {"message": "password=secret"}
        result = filter_event(event, config)
        self.assertIn(REDACT_PLACEHOLDER, result["message"])


class TestFieldFilter(unittest.TestCase):
    """Allowed fields filtering."""

    def test_no_filter_keeps_all(self):
        config = WhitelistConfig()
        event = {"source_id": "x", "message": "hi", "tags": {"a": 1}}
        result = filter_event(event, config)
        self.assertIn("tags", result)

    def test_keeps_only_allowed_fields(self):
        config = WhitelistConfig(allowed_fields=["source_id", "message"])
        event = {"source_id": "x", "message": "hi", "severity": "info", "tags": {}}
        result = filter_event(event, config)
        self.assertEqual(set(result.keys()), {"source_id", "message"})

    def test_missing_allowed_field_ok(self):
        config = WhitelistConfig(allowed_fields=["source_id", "nonexistent"])
        event = {"source_id": "x", "message": "hi"}
        result = filter_event(event, config)
        self.assertEqual(set(result.keys()), {"source_id"})


class TestFilterBatch(unittest.TestCase):
    """Batch filtering."""

    def test_no_config_returns_all(self):
        config = WhitelistConfig()
        events = [{"source_id": "a"}, {"source_id": "b"}]
        self.assertEqual(len(filter_batch(events, config)), 2)

    def test_filters_batch(self):
        config = WhitelistConfig(allowed_sources=["sap-*"])
        events = [
            {"source_id": "sap-01", "message": "ok"},
            {"source_id": "unknown", "message": "bad"},
            {"source_id": "sap-02", "message": "ok2"},
        ]
        result = filter_batch(events, config)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["source_id"], "sap-01")

    def test_combined_source_and_redaction(self):
        config = WhitelistConfig(
            allowed_sources=["sap-*"],
            blocked_patterns=[r"token=\S+"],
        )
        events = [
            {"source_id": "sap-01", "message": "auth token=abc123"},
            {"source_id": "scada-01", "message": "filtered out"},
        ]
        result = filter_batch(events, config)
        self.assertEqual(len(result), 1)
        self.assertNotIn("abc123", result[0]["message"])
