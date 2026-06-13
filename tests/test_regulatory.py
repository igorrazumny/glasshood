# File: tests/test_regulatory.py
# Purpose: Tests for regulatory mapping definitions

from src.compliance.regulatory import get_applicable_regulations, tag_finding, REGULATIONS


class TestGetApplicableRegulations:
    def test_rule_alert_maps_to_multiple(self):
        regs = get_applicable_regulations("rule_alert")
        ids = [r["id"] for r in regs]
        assert "annex_11_10.2" in ids
        assert "alcoa_attributable" in ids
        assert "21cfr_part11_11.10e" in ids

    def test_cve_finding_maps_to_security(self):
        regs = get_applicable_regulations("cve_finding")
        ids = [r["id"] for r in regs]
        assert "annex_11_10.2" in ids
        assert "21cfr_part11_11.10a" in ids

    def test_anomaly_maps_to_accuracy(self):
        regs = get_applicable_regulations("anomaly")
        ids = [r["id"] for r in regs]
        assert "alcoa_accurate" in ids
        assert "alcoa_contemporaneous" in ids

    def test_correlation_maps_correctly(self):
        regs = get_applicable_regulations("correlation")
        ids = [r["id"] for r in regs]
        assert "annex_11_10.2" in ids
        assert "21cfr_part11_11.10a" in ids

    def test_unknown_type_returns_empty(self):
        assert get_applicable_regulations("nonexistent") == []

    def test_all_regulations_have_required_fields(self):
        for reg_id, reg in REGULATIONS.items():
            assert "id" in reg
            assert "title" in reg
            assert "applies_to" in reg
            assert isinstance(reg["applies_to"], list)


class TestTagFinding:
    def test_adds_regulatory_refs(self):
        finding = {"severity": "critical", "message": "test"}
        tagged = tag_finding(finding, "rule_alert")
        assert "regulatory_refs" in tagged
        assert len(tagged["regulatory_refs"]) > 0
        assert "annex_11_10.2" in tagged["regulatory_refs"]

    def test_adds_finding_type(self):
        tagged = tag_finding({}, "cve_finding")
        assert tagged["finding_type"] == "cve_finding"

    def test_preserves_original_fields(self):
        finding = {"cve_id": "CVE-2024-0001", "severity": "high"}
        tagged = tag_finding(finding, "cve_finding")
        assert tagged["cve_id"] == "CVE-2024-0001"
        assert tagged["severity"] == "high"

    def test_does_not_mutate_original(self):
        finding = {"metric": "cpu"}
        tagged = tag_finding(finding, "anomaly")
        assert "regulatory_refs" not in finding
        assert "regulatory_refs" in tagged
