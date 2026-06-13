# File: tests/test_ingest_rules_integration.py
# Purpose: Integration test — ingested events trigger rules engine alerts

from unittest.mock import patch
import yaml

from src.ingest.processor import (
    process_batch, _events, _agent_heartbeats, _audit_log,
)
from src.rules.engine import get_alerts, _alerts, _audit_log as _rules_audit_log


def _reset():
    _events.clear()
    _agent_heartbeats.clear()
    _audit_log.clear()
    _alerts.clear()
    _rules_audit_log.clear()


class TestIngestRulesIntegration:
    def setup_method(self):
        _reset()

    def test_error_events_trigger_global_rule(self, tmp_path):
        rules_yaml = tmp_path / "rules.yaml"
        rules_yaml.write_text(yaml.dump({
            "rules": [{
                "id": "ingest_syslog_errors",
                "description": "High syslog error rate",
                "severity": "warning",
                "scope": "global",
                "condition": {
                    "source": "ingest_syslog",
                    "metric": "error_count",
                    "operator": ">",
                    "threshold": 2,
                },
            }]
        }))

        events = [
            {"source_id": "mw-01", "message": "err1", "source_type": "syslog", "severity": "error"},
            {"source_id": "mw-01", "message": "err2", "source_type": "syslog", "severity": "critical"},
            {"source_id": "mw-01", "message": "err3", "source_type": "syslog", "severity": "error"},
        ]

        with patch("src.config.settings.INGEST_RULES_ENABLED", True), \
             patch("src.config.settings.RULES_CONFIG_PATH", str(rules_yaml)):
            result = process_batch(events, "agent-1")

        assert result["accepted"] == 3
        alerts = get_alerts()
        warning_alerts = [a for a in alerts if a["severity"] == "warning"]
        assert len(warning_alerts) == 1
        assert "syslog error" in warning_alerts[0]["message"].lower()

    def test_info_events_dont_trigger_error_rule(self, tmp_path):
        rules_yaml = tmp_path / "rules.yaml"
        rules_yaml.write_text(yaml.dump({
            "rules": [{
                "id": "ingest_file_errors",
                "description": "High file error rate",
                "severity": "warning",
                "scope": "global",
                "condition": {
                    "source": "ingest_file",
                    "metric": "error_count",
                    "operator": ">",
                    "threshold": 0,
                },
            }]
        }))

        events = [
            {"source_id": "app.log", "message": "normal operation", "source_type": "file", "severity": "info"},
            {"source_id": "app.log", "message": "all good", "source_type": "file", "severity": "info"},
        ]

        with patch("src.config.settings.INGEST_RULES_ENABLED", True), \
             patch("src.config.settings.RULES_CONFIG_PATH", str(rules_yaml)):
            result = process_batch(events, "agent-1")

        assert result["accepted"] == 2
        alerts = get_alerts()
        assert len(alerts) == 0

    def test_rules_disabled_skips_evaluation(self):
        events = [
            {"source_id": "x", "message": "m", "source_type": "syslog", "severity": "error"},
        ]
        with patch("src.config.settings.INGEST_RULES_ENABLED", False):
            process_batch(events, "agent-1")
        alerts = get_alerts()
        assert len(alerts) == 0

    def test_snapshot_counts_by_source_type(self, tmp_path):
        rules_yaml = tmp_path / "rules.yaml"
        rules_yaml.write_text(yaml.dump({
            "rules": [{
                "id": "webhook_volume",
                "description": "High webhook volume",
                "severity": "info",
                "scope": "global",
                "condition": {
                    "source": "ingest_webhook",
                    "metric": "event_count",
                    "operator": ">",
                    "threshold": 1,
                },
            }]
        }))

        events = [
            {"source_id": "app", "message": "e1", "source_type": "webhook"},
            {"source_id": "app", "message": "e2", "source_type": "webhook"},
            {"source_id": "app", "message": "e3", "source_type": "webhook"},
            {"source_id": "log", "message": "e4", "source_type": "file"},
        ]

        with patch("src.config.settings.INGEST_RULES_ENABLED", True), \
             patch("src.config.settings.RULES_CONFIG_PATH", str(rules_yaml)):
            process_batch(events, "agent-1")

        alerts = get_alerts()
        assert len(alerts) == 1
        assert alerts[0]["rule_id"] == "webhook_volume"
