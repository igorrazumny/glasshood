# File: tests/test_report_engine.py
# Purpose: Tests for compliance report generation engine

from unittest.mock import patch

# Standard mock setup for evidence collection
_MOCK_EVIDENCE = {
    "collected_at": "2026-03-08T12:00:00+00:00",
    "period_start": None,
    "period_end": None,
    "current_state": {
        "alerts": [
            {"severity": "critical", "rule_id": "ram_critical",
             "regulatory_refs": ["annex_11_10.2", "alcoa_attributable", "alcoa_legible",
                                 "alcoa_contemporaneous", "alcoa_original", "alcoa_accurate",
                                 "21cfr_part11_11.10e"],
             "finding_type": "rule_alert"},
        ],
        "cve_findings": [
            {"severity": "high", "cve_id": "CVE-2024-001",
             "regulatory_refs": ["annex_11_10.2", "alcoa_attributable", "alcoa_legible",
                                 "alcoa_original", "21cfr_part11_11.10a", "21cfr_part11_11.10e"],
             "finding_type": "cve_finding"},
        ],
        "anomalies": [
            {"severity": "warning", "metric": "cpu",
             "regulatory_refs": ["annex_11_10.2", "alcoa_legible", "alcoa_contemporaneous",
                                 "alcoa_original", "alcoa_accurate", "21cfr_part11_11.10a"],
             "finding_type": "anomaly"},
        ],
    },
    "audit_trails": {
        "rules": [{"timestamp": "2026-03-08T12:00:00+00:00"}],
        "security": [],
        "anomalies": [{"timestamp": "2026-03-08T12:00:00+00:00"}],
        "correlations": [],
    },
    "summary": {
        "total_alerts": 1,
        "total_cve_findings": 1,
        "total_anomalies": 1,
        "cve_stats": {},
        "anomaly_stats": {},
        "severity_counts": {"critical": 1, "high": 1, "warning": 1},
        "audit_trail_entries": {"rules": 1, "security": 0, "anomalies": 1, "correlations": 0},
    },
}


def _reset_module():
    import src.compliance.report_engine as mod
    mod._report_counter = 0
    mod._audit_log.clear()


class TestGenerateReport:
    def setup_method(self):
        _reset_module()

    @patch("src.compliance.report_engine.collect_evidence", return_value=_MOCK_EVIDENCE)
    @patch("src.compliance.report_engine._load_config", return_value={"default_period_hours": 24})
    def test_full_report_structure(self, mock_config, mock_evidence):
        from src.compliance.report_engine import generate_report
        report = generate_report("full")

        assert "report_metadata" in report
        assert "executive_summary" in report
        assert "findings" in report
        assert "audit_trail_summary" in report
        assert "regulatory_coverage" in report

    @patch("src.compliance.report_engine.collect_evidence", return_value=_MOCK_EVIDENCE)
    @patch("src.compliance.report_engine._load_config", return_value={"default_period_hours": 24})
    def test_full_report_includes_all_findings(self, mock_config, mock_evidence):
        from src.compliance.report_engine import generate_report
        report = generate_report("full")

        assert report["executive_summary"]["total_findings"] == 3
        assert len(report["findings"]) == 3

    @patch("src.compliance.report_engine.collect_evidence", return_value=_MOCK_EVIDENCE)
    @patch("src.compliance.report_engine._load_config", return_value={"default_period_hours": 24})
    def test_annex_11_filters_findings(self, mock_config, mock_evidence):
        from src.compliance.report_engine import generate_report
        report = generate_report("annex_11")

        # All 3 findings have annex_11_10.2 in their regulatory_refs
        assert report["executive_summary"]["total_findings"] == 3
        for f in report["findings"]:
            assert any(r.startswith("annex_11") for r in f["regulatory_refs"])

    @patch("src.compliance.report_engine.collect_evidence", return_value=_MOCK_EVIDENCE)
    @patch("src.compliance.report_engine._load_config", return_value={"default_period_hours": 24})
    def test_21cfr_filters_findings(self, mock_config, mock_evidence):
        from src.compliance.report_engine import generate_report
        report = generate_report("21cfr_part11")

        for f in report["findings"]:
            assert any(r.startswith("21cfr_") for r in f["regulatory_refs"])

    @patch("src.compliance.report_engine.collect_evidence", return_value=_MOCK_EVIDENCE)
    @patch("src.compliance.report_engine._load_config", return_value={"default_period_hours": 24})
    def test_report_id_format(self, mock_config, mock_evidence):
        from src.compliance.report_engine import generate_report
        report = generate_report("full")

        assert report["report_metadata"]["report_id"].startswith("GH-RPT-")
        assert report["report_metadata"]["report_type"] == "full"

    @patch("src.compliance.report_engine.collect_evidence", return_value=_MOCK_EVIDENCE)
    @patch("src.compliance.report_engine._load_config", return_value={"default_period_hours": 24})
    def test_sequential_report_ids(self, mock_config, mock_evidence):
        from src.compliance.report_engine import generate_report
        r1 = generate_report("full")
        r2 = generate_report("full")

        id1 = r1["report_metadata"]["report_id"]
        id2 = r2["report_metadata"]["report_id"]
        assert id1 != id2
        assert id1.endswith("-001")
        assert id2.endswith("-002")


class TestComplianceStatus:
    def setup_method(self):
        _reset_module()

    @patch("src.compliance.report_engine.collect_evidence")
    @patch("src.compliance.report_engine._load_config", return_value={"default_period_hours": 24})
    def test_compliant_when_no_findings(self, mock_config, mock_evidence):
        mock_evidence.return_value = {
            **_MOCK_EVIDENCE,
            "current_state": {"alerts": [], "cve_findings": [], "anomalies": []},
        }
        from src.compliance.report_engine import generate_report
        report = generate_report("full")
        assert report["executive_summary"]["compliance_status"] == "compliant"

    @patch("src.compliance.report_engine.collect_evidence", return_value=_MOCK_EVIDENCE)
    @patch("src.compliance.report_engine._load_config", return_value={"default_period_hours": 24})
    def test_non_compliant_with_critical(self, mock_config, mock_evidence):
        from src.compliance.report_engine import generate_report
        report = generate_report("full")
        assert report["executive_summary"]["compliance_status"] == "non_compliant"

    @patch("src.compliance.report_engine.collect_evidence")
    @patch("src.compliance.report_engine._load_config", return_value={"default_period_hours": 24})
    def test_findings_present_without_critical(self, mock_config, mock_evidence):
        mock_evidence.return_value = {
            **_MOCK_EVIDENCE,
            "current_state": {
                "alerts": [{"severity": "warning", "regulatory_refs": ["annex_11_10.2"],
                            "finding_type": "rule_alert"}],
                "cve_findings": [],
                "anomalies": [],
            },
        }
        from src.compliance.report_engine import generate_report
        report = generate_report("full")
        assert report["executive_summary"]["compliance_status"] == "findings_present"


class TestReportAuditTrail:
    def setup_method(self):
        _reset_module()

    @patch("src.compliance.report_engine.collect_evidence", return_value=_MOCK_EVIDENCE)
    @patch("src.compliance.report_engine._load_config", return_value={"default_period_hours": 24})
    def test_generation_audit_trailed(self, mock_config, mock_evidence):
        from src.compliance.report_engine import generate_report, get_report_audit_log
        generate_report("full")
        log = get_report_audit_log()
        assert len(log) == 1
        assert log[0]["action"] == "generate_report"
        assert log[0]["report_type"] == "full"

    def test_available_report_types(self):
        from src.compliance.report_engine import get_available_report_types
        types = get_available_report_types()
        ids = [t["id"] for t in types]
        assert "annex_11" in ids
        assert "alcoa_plus" in ids
        assert "21cfr_part11" in ids
        assert "full" in ids
