# File: tests/test_gxp_scoring.py
# Purpose: Tests for GxP-aware CVE severity scoring

from src.security.gxp_scoring import score_severity


class TestScoreSeverity:
    def test_critical_cvss_gxp(self):
        assert score_severity(9.8, gxp_critical=True) == "critical"

    def test_critical_cvss_non_gxp(self):
        assert score_severity(9.8, gxp_critical=False) == "high"

    def test_high_cvss_gxp(self):
        assert score_severity(7.5, gxp_critical=True) == "high"

    def test_high_cvss_non_gxp(self):
        assert score_severity(7.5, gxp_critical=False) == "medium"

    def test_medium_cvss_gxp(self):
        assert score_severity(5.0, gxp_critical=True) == "medium"

    def test_medium_cvss_non_gxp(self):
        assert score_severity(5.0, gxp_critical=False) == "low"

    def test_low_cvss_gxp(self):
        assert score_severity(2.0, gxp_critical=True) == "low"

    def test_low_cvss_non_gxp(self):
        assert score_severity(2.0, gxp_critical=False) == "low"

    def test_boundary_nine(self):
        assert score_severity(9.0, gxp_critical=True) == "critical"
        assert score_severity(9.0, gxp_critical=False) == "high"

    def test_boundary_seven(self):
        assert score_severity(7.0, gxp_critical=True) == "high"
        assert score_severity(7.0, gxp_critical=False) == "medium"

    def test_boundary_four(self):
        assert score_severity(4.0, gxp_critical=True) == "medium"
        assert score_severity(4.0, gxp_critical=False) == "low"

    def test_zero_score(self):
        assert score_severity(0.0, gxp_critical=True) == "low"
        assert score_severity(0.0, gxp_critical=False) == "low"
