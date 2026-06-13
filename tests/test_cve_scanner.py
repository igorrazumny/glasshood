# File: tests/test_cve_scanner.py
# Purpose: Tests for CVE scanner — NVD API queries and component matching

import os
import tempfile
from unittest.mock import patch, MagicMock

import pytest
import yaml

from src.models.finding import SecurityFinding


def _reset_module():
    """Reset module globals between tests."""
    import src.security.cve_scanner as mod
    mod._findings = []
    mod._last_poll = 0
    mod._audit_log.clear()


# Sample NVD API response for testing
SAMPLE_NVD_RESPONSE = {
    "vulnerabilities": [
        {
            "cve": {
                "id": "CVE-2024-1234",
                "descriptions": [
                    {"lang": "en", "value": "Test vulnerability in component X"}
                ],
                "metrics": {
                    "cvssMetricV31": [{
                        "cvssData": {
                            "baseScore": 8.1,
                            "baseSeverity": "HIGH",
                        }
                    }]
                },
            }
        },
        {
            "cve": {
                "id": "CVE-2024-5678",
                "descriptions": [
                    {"lang": "en", "value": "Critical RCE in component X"}
                ],
                "metrics": {
                    "cvssMetricV31": [{
                        "cvssData": {
                            "baseScore": 9.8,
                            "baseSeverity": "CRITICAL",
                        }
                    }]
                },
            }
        },
    ]
}


class TestLoadComponents:
    def test_loads_valid_yaml(self):
        from src.security.cve_scanner import _load_components
        scan_config, components = _load_components("config/security_scan.yaml")
        assert len(components) > 0
        assert all("id" in c for c in components)
        assert scan_config.get("enabled") is True

    def test_missing_file_returns_empty(self):
        from src.security.cve_scanner import _load_components
        scan_config, components = _load_components("/nonexistent/scan.yaml")
        assert scan_config == {}
        assert components == []

    def test_empty_file_returns_empty(self):
        from src.security.cve_scanner import _load_components
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("")
            path = f.name
        try:
            scan_config, components = _load_components(path)
            assert components == []
        finally:
            os.unlink(path)


class TestQueryNvd:
    @patch("src.security.cve_scanner.requests.get")
    def test_returns_vulnerabilities(self, mock_get):
        from src.security.cve_scanner import _query_nvd
        mock_resp = MagicMock()
        mock_resp.json.return_value = SAMPLE_NVD_RESPONSE
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        vulns = _query_nvd("cpe:2.3:a:test:test:1.0:*:*:*:*:*:*:*")
        assert len(vulns) == 2
        mock_get.assert_called_once()

    @patch("src.security.cve_scanner.requests.get")
    def test_empty_results(self, mock_get):
        from src.security.cve_scanner import _query_nvd
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"vulnerabilities": []}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        vulns = _query_nvd("cpe:2.3:a:test:test:1.0:*:*:*:*:*:*:*")
        assert vulns == []

    @patch("src.security.cve_scanner.requests.get")
    def test_api_error_returns_empty(self, mock_get):
        from src.security.cve_scanner import _query_nvd
        import requests
        mock_get.side_effect = requests.RequestException("timeout")
        vulns = _query_nvd("cpe:2.3:a:test:test:1.0:*:*:*:*:*:*:*")
        assert vulns == []


class TestParseCvss:
    def test_cvss_v31(self):
        from src.security.cve_scanner import _parse_cvss
        score, severity = _parse_cvss(SAMPLE_NVD_RESPONSE["vulnerabilities"][0])
        assert score == 8.1
        assert severity == "high"

    def test_cvss_critical(self):
        from src.security.cve_scanner import _parse_cvss
        score, severity = _parse_cvss(SAMPLE_NVD_RESPONSE["vulnerabilities"][1])
        assert score == 9.8
        assert severity == "critical"

    def test_no_metrics_returns_zero(self):
        from src.security.cve_scanner import _parse_cvss
        score, severity = _parse_cvss({"cve": {"metrics": {}}})
        assert score == 0.0
        assert severity == "low"


class TestScanComponent:
    @patch("src.security.cve_scanner._query_nvd")
    def test_returns_findings(self, mock_query):
        from src.security.cve_scanner import _scan_component
        mock_query.return_value = SAMPLE_NVD_RESPONSE["vulnerabilities"]
        component = {
            "id": "test-comp",
            "name": "Test Component 1.0",
            "cpe": "cpe:2.3:a:test:test:1.0:*:*:*:*:*:*:*",
            "node_ids": ["vm-1"],
            "gxp_critical": True,
        }
        findings = _scan_component(component)
        assert len(findings) == 2
        assert findings[0].cve_id == "CVE-2024-1234"
        assert findings[0].component_id == "test-comp"
        assert findings[0].gxp_critical is True
        assert findings[0].node_ids == ["vm-1"]

    @patch("src.security.cve_scanner._query_nvd")
    def test_no_cpe_returns_empty(self, mock_query):
        from src.security.cve_scanner import _scan_component
        findings = _scan_component({"id": "no-cpe", "name": "No CPE"})
        assert findings == []
        mock_query.assert_not_called()


class TestGetFindings:
    def setup_method(self):
        _reset_module()

    @patch("src.security.cve_scanner._load_components")
    @patch("src.security.cve_scanner._scan_component")
    @patch("src.security.cve_scanner.time.sleep")
    def test_poll_once_caches_findings(self, mock_sleep, mock_scan, mock_load):
        from src.security.cve_scanner import poll_once, get_findings
        mock_load.return_value = (
            {"enabled": True},
            [{"id": "comp-1", "cpe": "cpe:2.3:a:test:test:1.0:*:*:*:*:*:*:*"}]
        )
        mock_scan.return_value = [
            SecurityFinding(
                cve_id="CVE-2024-9999", severity="high", cvss_score=7.5,
                description="Test vuln", component_id="comp-1",
                component_name="Test", discovered_at="2026-03-08T00:00:00",
            )
        ]
        poll_once()
        findings = get_findings()
        assert len(findings) == 1
        assert findings[0]["cve_id"] == "CVE-2024-9999"
        assert isinstance(findings[0], dict)

    def test_empty_findings(self):
        from src.security.cve_scanner import get_findings
        assert get_findings() == []


class TestGetStats:
    def setup_method(self):
        _reset_module()

    def test_stats_counts(self):
        import src.security.cve_scanner as mod
        mod._findings = [
            SecurityFinding(cve_id="CVE-1", severity="critical", cvss_score=9.8,
                            description="", component_id="c1", component_name="C1",
                            gxp_critical=True, discovered_at=""),
            SecurityFinding(cve_id="CVE-2", severity="high", cvss_score=7.5,
                            description="", component_id="c2", component_name="C2",
                            discovered_at=""),
            SecurityFinding(cve_id="CVE-3", severity="high", cvss_score=8.0,
                            description="", component_id="c3", component_name="C3",
                            gxp_critical=True, discovered_at=""),
        ]
        stats = mod.get_stats()
        assert stats["total"] == 3
        assert stats["critical_gxp_count"] == 1
        assert stats["high_count"] == 2
        assert stats["open_count"] == 3


class TestUpdateFindingStatus:
    def setup_method(self):
        _reset_module()

    def test_acknowledge_finding(self):
        import src.security.cve_scanner as mod
        mod._findings = [
            SecurityFinding(cve_id="CVE-2024-1234", severity="high", cvss_score=8.1,
                            description="Test", component_id="c1", component_name="C1",
                            discovered_at="2026-03-08T00:00:00"),
        ]
        result = mod.update_finding_status("CVE-2024-1234", "acknowledged", "auditor@pharma.com")
        assert result is True
        assert mod._findings[0].status == "acknowledged"
        assert mod._findings[0].status_changed_by == "auditor@pharma.com"
        assert mod._findings[0].status_changed_at is not None

    def test_mitigate_finding(self):
        import src.security.cve_scanner as mod
        mod._findings = [
            SecurityFinding(cve_id="CVE-2024-5678", severity="critical", cvss_score=9.8,
                            description="Test", component_id="c1", component_name="C1",
                            discovered_at="2026-03-08T00:00:00"),
        ]
        assert mod.update_finding_status("CVE-2024-5678", "mitigated", "ops@pharma.com") is True
        assert mod._findings[0].status == "mitigated"

    def test_nonexistent_cve_returns_false(self):
        import src.security.cve_scanner as mod
        assert mod.update_finding_status("CVE-9999-0000", "acknowledged", "user") is False

    def test_invalid_status_returns_false(self):
        import src.security.cve_scanner as mod
        mod._findings = [
            SecurityFinding(cve_id="CVE-2024-1234", severity="high", cvss_score=8.1,
                            description="Test", component_id="c1", component_name="C1",
                            discovered_at="2026-03-08T00:00:00"),
        ]
        assert mod.update_finding_status("CVE-2024-1234", "invalid_status", "user") is False

    def test_status_change_audit_trailed(self):
        import src.security.cve_scanner as mod
        mod._findings = [
            SecurityFinding(cve_id="CVE-2024-1234", severity="high", cvss_score=8.1,
                            description="Test", component_id="c1", component_name="C1",
                            discovered_at="2026-03-08T00:00:00"),
        ]
        mod.update_finding_status("CVE-2024-1234", "accepted", "ciso@pharma.com")
        log = list(mod._audit_log)
        assert len(log) == 1
        assert log[0]["action"] == "status_change"
        assert log[0]["cve_id"] == "CVE-2024-1234"
        assert log[0]["changed_by"] == "ciso@pharma.com"
