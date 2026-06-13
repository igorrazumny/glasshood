# File: tests/test_evidence.py
# Purpose: Tests for evidence aggregation from all monitoring sources

from unittest.mock import patch
from datetime import datetime, timezone, timedelta


class TestCollectEvidence:
    @patch("src.security.correlator.get_audit_log", return_value=[])
    @patch("src.security.anomaly_detector.get_audit_log", return_value=[])
    @patch("src.security.cve_scanner.get_audit_log", return_value=[])
    @patch("src.rules.engine.get_audit_log", return_value=[])
    @patch("src.security.anomaly_detector.get_stats", return_value={"anomaly_count": 1})
    @patch("src.security.cve_scanner.get_stats", return_value={"total": 1})
    @patch("src.security.anomaly_detector.get_anomalies",
           return_value=[{"severity": "critical", "metric": "cpu"}])
    @patch("src.security.cve_scanner.get_findings",
           return_value=[{"severity": "high", "cve_id": "CVE-2024-001"}])
    @patch("src.rules.engine.get_alerts",
           return_value=[{"severity": "warning", "rule_id": "ram_high"}])
    def test_aggregates_all_sources(self, *mocks):
        from src.compliance.evidence import collect_evidence
        result = collect_evidence()

        assert len(result["current_state"]["alerts"]) == 1
        assert len(result["current_state"]["cve_findings"]) == 1
        assert len(result["current_state"]["anomalies"]) == 1
        assert result["summary"]["total_alerts"] == 1
        assert result["summary"]["total_cve_findings"] == 1
        assert result["summary"]["total_anomalies"] == 1

    @patch("src.security.correlator.get_audit_log", return_value=[])
    @patch("src.security.anomaly_detector.get_audit_log", return_value=[])
    @patch("src.security.cve_scanner.get_audit_log", return_value=[])
    @patch("src.rules.engine.get_audit_log", return_value=[])
    @patch("src.security.anomaly_detector.get_stats", return_value={})
    @patch("src.security.cve_scanner.get_stats", return_value={})
    @patch("src.security.anomaly_detector.get_anomalies", return_value=[])
    @patch("src.security.cve_scanner.get_findings", return_value=[])
    @patch("src.rules.engine.get_alerts",
           return_value=[{"severity": "warning"}])
    def test_tags_findings_with_regulations(self, *mocks):
        from src.compliance.evidence import collect_evidence
        result = collect_evidence()

        alert = result["current_state"]["alerts"][0]
        assert "regulatory_refs" in alert
        assert "annex_11_10.2" in alert["regulatory_refs"]

    @patch("src.security.correlator.get_audit_log", return_value=[])
    @patch("src.security.anomaly_detector.get_audit_log", return_value=[])
    @patch("src.security.cve_scanner.get_audit_log", return_value=[])
    @patch("src.rules.engine.get_audit_log", return_value=[])
    @patch("src.security.anomaly_detector.get_stats", return_value={})
    @patch("src.security.cve_scanner.get_stats", return_value={})
    @patch("src.security.anomaly_detector.get_anomalies", return_value=[])
    @patch("src.security.cve_scanner.get_findings", return_value=[])
    @patch("src.rules.engine.get_alerts", return_value=[])
    def test_empty_sources_returns_empty(self, *mocks):
        from src.compliance.evidence import collect_evidence
        result = collect_evidence()

        assert result["summary"]["total_alerts"] == 0
        assert result["summary"]["total_cve_findings"] == 0
        assert result["summary"]["total_anomalies"] == 0

    @patch("src.security.correlator.get_audit_log", return_value=[])
    @patch("src.security.anomaly_detector.get_audit_log", return_value=[])
    @patch("src.security.cve_scanner.get_audit_log", return_value=[])
    @patch("src.rules.engine.get_audit_log", return_value=[])
    @patch("src.security.anomaly_detector.get_stats", return_value={})
    @patch("src.security.cve_scanner.get_stats", return_value={})
    @patch("src.security.anomaly_detector.get_anomalies", return_value=[])
    @patch("src.security.cve_scanner.get_findings", return_value=[])
    @patch("src.rules.engine.get_alerts", return_value=[])
    def test_severity_counts(self, *mocks):
        # mocks[0] = get_alerts (innermost decorator = first positional arg)
        mocks[0].return_value = [
            {"severity": "critical", "rule_id": "a"},
            {"severity": "warning", "rule_id": "b"},
            {"severity": "critical", "rule_id": "c"},
        ]
        from src.compliance.evidence import collect_evidence
        result = collect_evidence()

        counts = result["summary"]["severity_counts"]
        assert counts["critical"] == 2
        assert counts["warning"] == 1


class TestPeriodFiltering:
    def test_filters_audit_entries(self):
        from src.compliance.evidence import _filter_by_period

        now = datetime.now(timezone.utc)
        entries = [
            {"timestamp": (now - timedelta(hours=2)).isoformat(), "action": "old"},
            {"timestamp": (now - timedelta(minutes=30)).isoformat(), "action": "recent"},
            {"timestamp": now.isoformat(), "action": "now"},
        ]
        start = (now - timedelta(hours=1)).isoformat()
        filtered = _filter_by_period(entries, period_start=start)
        assert len(filtered) == 2

    def test_no_period_returns_all(self):
        from src.compliance.evidence import _filter_by_period

        entries = [{"timestamp": "2026-01-01T00:00:00+00:00"}]
        assert _filter_by_period(entries) == entries

    def test_handles_missing_timestamps(self):
        from src.compliance.evidence import _filter_by_period

        entries = [{"action": "no_timestamp"}, {"timestamp": "", "action": "empty"}]
        start = "2026-01-01T00:00:00+00:00"
        filtered = _filter_by_period(entries, period_start=start)
        assert len(filtered) == 0
