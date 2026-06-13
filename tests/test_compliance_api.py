# File: tests/test_compliance_api.py
# Purpose: Tests for compliance API routes and audit trail endpoints

from unittest.mock import patch, MagicMock

from src.api.routes.compliance import list_report_types, create_report, compliance_audit_log
from src.api.routes.audit import (
    security_audit_log, anomaly_audit_log, correlation_audit_log,
)


def _mock_request():
    return MagicMock()


class TestComplianceRoutes:
    @patch("src.api.routes.compliance.verify_token")
    def test_list_report_types(self, mock_auth):
        result = list_report_types(_mock_request())
        assert "report_types" in result
        ids = [t["id"] for t in result["report_types"]]
        assert "full" in ids
        assert "annex_11" in ids

    @patch("src.api.routes.compliance.verify_token")
    @patch("src.compliance.report_engine.collect_evidence")
    @patch("src.compliance.report_engine._load_config",
           return_value={"default_period_hours": 24})
    def test_create_report_returns_report(self, mock_config, mock_evidence, mock_auth):
        mock_evidence.return_value = {
            "collected_at": "2026-03-08T12:00:00+00:00",
            "period_start": None, "period_end": None,
            "current_state": {"alerts": [], "cve_findings": [], "anomalies": []},
            "audit_trails": {"rules": [], "security": [], "anomalies": [], "correlations": []},
            "summary": {
                "total_alerts": 0, "total_cve_findings": 0, "total_anomalies": 0,
                "cve_stats": {}, "anomaly_stats": {}, "severity_counts": {},
                "audit_trail_entries": {"rules": 0, "security": 0, "anomalies": 0, "correlations": 0},
            },
        }
        # Reset report counter
        import src.compliance.report_engine as mod
        mod._report_counter = 0
        mod._audit_log.clear()

        result = create_report(_mock_request(), report_type="full")
        assert "report_metadata" in result
        assert result["report_metadata"]["report_type"] == "full"
        assert result["executive_summary"]["compliance_status"] == "compliant"

    @patch("src.api.routes.compliance.verify_token")
    def test_invalid_report_type_raises(self, mock_auth):
        import pytest
        with pytest.raises(Exception):  # HTTPException
            create_report(_mock_request(), report_type="invalid_type")

    @patch("src.api.routes.compliance.verify_token")
    def test_compliance_audit_log_empty(self, mock_auth):
        import src.compliance.report_engine as mod
        mod._audit_log.clear()

        result = compliance_audit_log(_mock_request(), limit=50)
        assert result["entries"] == []
        assert result["count"] == 0


class TestAuditEndpoints:
    @patch("src.api.routes.audit.verify_token")
    @patch("src.api.routes.audit.get_cve_audit_log", return_value=[
        {"timestamp": "2026-03-08T12:00:00+00:00", "action": "scan"}
    ])
    def test_security_audit_returns_entries(self, mock_audit, mock_auth):
        result = security_audit_log(_mock_request(), limit=50)
        assert result["count"] == 1
        assert result["entries"][0]["action"] == "scan"

    @patch("src.api.routes.audit.verify_token")
    @patch("src.api.routes.audit.get_anomaly_audit_log", return_value=[
        {"timestamp": "2026-03-08T12:00:00+00:00", "action": "detect"}
    ])
    def test_anomaly_audit_returns_entries(self, mock_audit, mock_auth):
        result = anomaly_audit_log(_mock_request(), limit=50)
        assert result["count"] == 1

    @patch("src.api.routes.audit.verify_token")
    @patch("src.api.routes.audit.get_correlator_audit_log", return_value=[])
    def test_correlation_audit_empty(self, mock_audit, mock_auth):
        result = correlation_audit_log(_mock_request(), limit=50)
        assert result["count"] == 0

    @patch("src.api.routes.audit.verify_token")
    @patch("src.api.routes.audit.get_cve_audit_log",
           return_value=[{"a": i} for i in range(100)])
    def test_limit_parameter(self, mock_audit, mock_auth):
        result = security_audit_log(_mock_request(), limit=10)
        assert result["count"] == 10
