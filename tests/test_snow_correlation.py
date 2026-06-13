# File: tests/test_snow_correlation.py
# Purpose: Tests for SNOW correlation engine — pure functions, no mocking needed

from datetime import datetime, timezone, timedelta

from src.integrations.correlation import (
    correlate_with_incidents, correlate_with_changes, surface_patterns,
)


def _alert(rule_id="mem_high", node_id="middleware-01", severity="critical",
           age_seconds=0):
    ts = (datetime.now(timezone.utc) - timedelta(seconds=age_seconds)).isoformat()
    return {"rule_id": rule_id, "node_id": node_id, "severity": severity,
            "triggered_at": ts}


def _incident(sys_id="INC001", number="INC0001001", cmdb_ci="",
              age_seconds=0):
    ts = (datetime.now(timezone.utc) - timedelta(seconds=age_seconds)).isoformat()
    return {"sys_id": sys_id, "number": number, "short_description": "Memory issue",
            "state": "1", "cmdb_ci": cmdb_ci, "opened_at": ts}


def _change(sys_id="CHG001", number="CHG0001001", cmdb_ci="",
            age_seconds=600):
    ts = (datetime.now(timezone.utc) - timedelta(seconds=age_seconds)).isoformat()
    return {"sys_id": sys_id, "number": number, "short_description": "Firewall update",
            "state": "3", "cmdb_ci": cmdb_ci, "start_date": ts}


class TestCorrelateWithIncidents:
    def test_matches_within_window(self):
        alert = _alert(age_seconds=60)
        incident = _incident(age_seconds=120)
        result = correlate_with_incidents([alert], [incident], {}, time_window_seconds=300)
        assert len(result) == 1
        assert result[0]["type"] == "alert_incident"
        assert result[0]["snow_sys_id"] == "INC001"

    def test_no_match_outside_window(self):
        alert = _alert(age_seconds=0)
        incident = _incident(age_seconds=3600)
        result = correlate_with_incidents([alert], [incident], {}, time_window_seconds=300)
        assert result == []

    def test_system_filter_matching_cmdb(self):
        alert = _alert(node_id="middleware-01")
        incident = _incident(cmdb_ci="SAP-MW-01", age_seconds=60)
        mapping = {"middleware-01": "SAP-MW-01"}
        result = correlate_with_incidents([alert], [incident], mapping)
        assert len(result) == 1

    def test_system_filter_excludes_wrong_cmdb(self):
        alert = _alert(node_id="middleware-01")
        incident = _incident(cmdb_ci="OTHER-SYS", age_seconds=60)
        mapping = {"middleware-01": "SAP-MW-01"}
        result = correlate_with_incidents([alert], [incident], mapping)
        assert result == []

    def test_empty_inputs(self):
        assert correlate_with_incidents([], [], {}) == []
        assert correlate_with_incidents([_alert()], [], {}) == []
        assert correlate_with_incidents([], [_incident()], {}) == []

    def test_bad_timestamp_skipped(self):
        alert = {"rule_id": "x", "node_id": "n", "triggered_at": "not-a-date"}
        result = correlate_with_incidents([alert], [_incident()], {})
        assert result == []


class TestCorrelateWithChanges:
    def test_change_before_alert_correlates(self):
        alert = _alert(age_seconds=0)
        change = _change(age_seconds=600)  # 10 min ago
        result = correlate_with_changes([alert], [change], {}, lookback_seconds=3600)
        assert len(result) == 1
        assert result[0]["type"] == "change_caused_alert"
        assert result[0]["cause_confidence"] == "high"  # 600s < 900 threshold

    def test_very_close_change_is_high_confidence(self):
        alert = _alert(age_seconds=0)
        change = _change(age_seconds=300)  # 5 min before alert
        result = correlate_with_changes([alert], [change], {}, lookback_seconds=3600)
        assert len(result) == 1
        assert result[0]["cause_confidence"] == "high"  # 300s < 900

    def test_alert_before_change_no_match(self):
        # Alert 20 min ago, change 10 min ago — alert came first, not causal
        alert = _alert(age_seconds=1200)
        change = _change(age_seconds=600)
        result = correlate_with_changes([alert], [change], {}, lookback_seconds=3600)
        assert result == []

    def test_outside_lookback_no_match(self):
        alert = _alert(age_seconds=0)
        change = _change(age_seconds=7200)  # 2h ago
        result = correlate_with_changes([alert], [change], {}, lookback_seconds=3600)
        assert result == []

    def test_empty_inputs(self):
        assert correlate_with_changes([], [], {}) == []


class TestSurfacePatterns:
    def test_multiple_incidents_surfaced(self):
        corrs = [
            {"alert_node_id": "mw-01", "snow_sys_id": "INC001"},
            {"alert_node_id": "mw-01", "snow_sys_id": "INC002"},
            {"alert_node_id": "mw-01", "snow_sys_id": "INC003"},
        ]
        result = surface_patterns(corrs, [])
        assert len(result) == 1
        assert result[0]["node_id"] == "mw-01"
        assert result[0]["incident_ticket_count"] == 3
        assert result[0]["significance"] == "high"
        assert result[0]["pattern_type"] == "repeated_incidents"

    def test_single_ticket_not_surfaced(self):
        corrs = [{"alert_node_id": "sap-01", "snow_sys_id": "INC001"}]
        assert surface_patterns(corrs, []) == []

    def test_mixed_incidents_and_changes(self):
        inc = [{"alert_node_id": "node-A", "snow_sys_id": "INC001"}]
        chg = [{"alert_node_id": "node-A", "snow_sys_id": "CHG001"}]
        result = surface_patterns(inc, chg)
        assert len(result) == 1
        assert result[0]["total_ticket_count"] == 2
        assert result[0]["pattern_type"] == "change_induced_incidents"

    def test_sorted_by_ticket_count(self):
        corrs = [
            {"alert_node_id": "node-A", "snow_sys_id": "INC001"},
            {"alert_node_id": "node-A", "snow_sys_id": "INC002"},
            {"alert_node_id": "node-B", "snow_sys_id": "INC003"},
            {"alert_node_id": "node-B", "snow_sys_id": "INC004"},
            {"alert_node_id": "node-B", "snow_sys_id": "INC005"},
        ]
        result = surface_patterns(corrs, [])
        assert result[0]["node_id"] == "node-B"   # 3 tickets first
        assert result[1]["node_id"] == "node-A"    # 2 tickets second

    def test_empty_inputs(self):
        assert surface_patterns([], []) == []
