# File: tests/test_snow_sync.py
# Purpose: Tests for SNOW sync engine — mock ServiceNowClient throughout

from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from src.integrations.servicenow import ServiceNowClient


def _reset_sync():
    import src.integrations.sync as mod
    mod._sync_state = {}
    mod._correlation_results = {
        "incident_correlations": [], "change_correlations": [],
        "patterns": [], "timestamp": None,
    }
    mod._audit_log.clear()


class TestPushAlertsToSnow:
    def setup_method(self):
        _reset_sync()

    def test_pushes_critical_alert(self):
        from src.integrations.sync import push_alerts_to_snow

        client = MagicMock(spec=ServiceNowClient)
        client.create_incident.return_value = "SYS001"

        alert = {
            "rule_id": "mem_high", "node_id": "vm-1", "severity": "critical",
            "message": "High memory",
            "triggered_at": datetime.now(timezone.utc).isoformat(),
            "acknowledged": False,
        }
        result = push_alerts_to_snow([alert], client, {})
        assert "SYS001" in result
        client.create_incident.assert_called_once()

    def test_skips_acknowledged_alert(self):
        from src.integrations.sync import push_alerts_to_snow

        client = MagicMock(spec=ServiceNowClient)
        alert = {
            "rule_id": "mem_high", "node_id": "vm-1", "severity": "critical",
            "triggered_at": datetime.now(timezone.utc).isoformat(),
            "acknowledged": True,
        }
        result = push_alerts_to_snow([alert], client, {})
        client.create_incident.assert_not_called()
        assert result == []

    def test_skips_info_severity(self):
        from src.integrations.sync import push_alerts_to_snow

        client = MagicMock(spec=ServiceNowClient)
        alert = {
            "rule_id": "info_rule", "node_id": "vm-1", "severity": "info",
            "triggered_at": datetime.now(timezone.utc).isoformat(),
            "acknowledged": False,
        }
        result = push_alerts_to_snow([alert], client, {})
        client.create_incident.assert_not_called()
        assert result == []

    def test_deduplicates_already_synced(self):
        import src.integrations.sync as mod
        from src.integrations.sync import push_alerts_to_snow

        mod._sync_state["mem_high:vm-1"] = {
            "snow_sys_id": "SYS001", "synced_at": "...",
        }
        client = MagicMock(spec=ServiceNowClient)
        alert = {
            "rule_id": "mem_high", "node_id": "vm-1", "severity": "critical",
            "triggered_at": datetime.now(timezone.utc).isoformat(),
            "acknowledged": False,
        }
        result = push_alerts_to_snow([alert], client, {})
        client.create_incident.assert_not_called()
        assert result == []

    def test_pushes_warning_alert(self):
        from src.integrations.sync import push_alerts_to_snow

        client = MagicMock(spec=ServiceNowClient)
        client.create_incident.return_value = "SYS002"

        alert = {
            "rule_id": "cpu_warn", "node_id": "vm-2", "severity": "warning",
            "message": "CPU warning",
            "triggered_at": datetime.now(timezone.utc).isoformat(),
            "acknowledged": False,
        }
        result = push_alerts_to_snow([alert], client, {})
        assert "SYS002" in result


class TestSyncOnce:
    def setup_method(self):
        _reset_sync()

    def test_noop_when_disabled(self):
        with patch("src.integrations.sync.SNOW_ENABLED", False):
            from src.integrations.sync import sync_once
            sync_once()  # should not raise


class TestBuildPayload:
    def test_maps_severity_to_urgency(self):
        from src.integrations.sync import _build_incident_payload

        severity_map = {"critical": {"urgency": 1, "impact": 1}}
        alert = {"rule_id": "r1", "severity": "critical", "message": "test",
                 "node_id": "vm-1", "triggered_at": "2026-01-01"}

        payload = _build_incident_payload(alert, severity_map)
        assert payload["urgency"] == "1"
        assert payload["impact"] == "1"
        assert "GlassHood" in payload["short_description"]

    def test_default_mapping_for_unknown_severity(self):
        from src.integrations.sync import _build_incident_payload

        payload = _build_incident_payload(
            {"rule_id": "r1", "severity": "unknown", "message": "test"},
            {},
        )
        assert payload["urgency"] == "2"  # default
