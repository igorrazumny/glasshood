# File: tests/test_rules_engine.py
# Purpose: Tests for Layer 1 deterministic rule engine

import os
import time
import tempfile
from unittest.mock import patch

import pytest
import yaml

from src.models.topology import Node


def _reset_module():
    """Reset module globals between tests."""
    import src.rules.engine as mod
    mod._active.clear()
    mod._resolved.clear()
    mod._rule_checked_at.clear()
    mod._rule_names.clear()
    mod._audit_log.clear()


class TestLoadRules:
    def test_loads_valid_yaml(self):
        from src.rules.engine import load_rules
        rules = load_rules("config/rules.yaml")
        assert len(rules) > 0
        assert all("id" in r for r in rules)

    def test_missing_file_returns_empty(self):
        from src.rules.engine import load_rules
        rules = load_rules("/nonexistent/rules.yaml")
        assert rules == []

    def test_empty_file_returns_empty(self):
        from src.rules.engine import load_rules
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("")
            path = f.name
        try:
            rules = load_rules(path)
            assert rules == []
        finally:
            os.unlink(path)


class TestCheckNodeRule:
    def test_fires_on_threshold_breach(self):
        from src.rules.engine import _check_node_rule
        rule = {"id": "ram_high", "severity": "warning", "description": "High RAM",
                "scope": "node", "node_types": ["vm"],
                "condition": {"metric": "ram_percent", "operator": ">", "threshold": 85}}
        node = Node(id="vm-1", label="VM", type="vm", status="healthy",
                    metrics={"ram_percent": 90.0})
        checked, alert = _check_node_rule(rule, node)
        assert checked and alert is not None
        assert alert.rule_id == "ram_high"
        assert alert.severity == "warning"
        assert alert.metric_value == 90.0
        assert alert.threshold == 85.0

    def test_skips_below_threshold(self):
        from src.rules.engine import _check_node_rule
        rule = {"id": "ram_high", "severity": "warning",
                "scope": "node", "node_types": ["vm"],
                "condition": {"metric": "ram_percent", "operator": ">", "threshold": 85}}
        node = Node(id="vm-1", label="VM", type="vm", status="healthy",
                    metrics={"ram_percent": 60.0})
        assert _check_node_rule(rule, node) == (True, None)

    def test_skips_wrong_node_type(self):
        from src.rules.engine import _check_node_rule
        rule = {"id": "ram_high", "severity": "warning",
                "scope": "node", "node_types": ["vm"],
                "condition": {"metric": "ram_percent", "operator": ">", "threshold": 85}}
        node = Node(id="nginx", label="nginx", type="nginx", status="healthy",
                    metrics={"ram_percent": 99.0})
        assert _check_node_rule(rule, node) == (False, None)

    def test_status_equality_check(self):
        from src.rules.engine import _check_node_rule
        rule = {"id": "node_error", "severity": "critical", "description": "Node error",
                "scope": "node",
                "condition": {"metric": "status", "operator": "==", "value": "error"}}
        node = Node(id="vm-1", label="VM", type="vm", status="error")
        checked, alert = _check_node_rule(rule, node)
        assert checked and alert is not None
        assert alert.severity == "critical"

    def test_missing_metric_returns_none(self):
        from src.rules.engine import _check_node_rule
        rule = {"id": "ram_high", "severity": "warning",
                "scope": "node",
                "condition": {"metric": "ram_percent", "operator": ">", "threshold": 85}}
        node = Node(id="vm-1", label="VM", type="vm", status="healthy", metrics={})
        # No data: not checked (REQ-GHA-027 clause 6)
        assert _check_node_rule(rule, node) == (False, None)


class TestCheckGlobalRule:
    def test_fires_on_global_threshold(self):
        from src.rules.engine import _check_global_rule
        rule = {"id": "error_spike", "severity": "warning", "description": "Errors",
                "scope": "global",
                "condition": {"source": "logging", "metric": "error_count_15m",
                              "operator": ">", "threshold": 5}}
        snapshot = {"logging": {"error_count_15m": 12, "part": "cv-mig"}}
        key, alert = _check_global_rule(rule, snapshot, {"cv-mig": "Confidential VM (MIG)"})
        assert key == ("error_spike", "cv-mig")
        assert alert.metric_value == 12.0
        assert alert.node_id == "cv-mig"
        assert alert.part_label == "Confidential VM (MIG)"

    def test_skips_below_global_threshold(self):
        from src.rules.engine import _check_global_rule
        rule = {"id": "error_spike", "severity": "warning",
                "scope": "global",
                "condition": {"source": "logging", "metric": "error_count_15m",
                              "operator": ">", "threshold": 5}}
        snapshot = {"logging": {"error_count_15m": 2, "part": "cv-mig"}}
        assert _check_global_rule(rule, snapshot, {}) == (("error_spike", "cv-mig"), None)

    def test_without_part_is_not_checked(self):
        """REQ-GHA-027 clause 3: a signal not tied to a part of the system raises nothing."""
        from src.rules.engine import _check_global_rule
        rule = {"id": "error_spike", "severity": "warning", "scope": "global",
                "condition": {"source": "logging", "metric": "error_count_15m",
                              "operator": ">", "threshold": 5}}
        assert _check_global_rule(rule, {"logging": {"error_count_15m": 50}}, {}) == (None, None)


class TestAnomalyClassificationPerAlert:
    """REQ-004: classification is snapshot per-Alert at creation, classify
    failures are caught, Alert.message keeps the metric detail."""

    def _anomaly_rule(self):
        return {"id": "anomaly_detected", "severity": "warning",
                "description": "Anomaly detected", "scope": "global", "per_anomaly": True,
                "groups": {"error_count_15m": "errors"},
                "condition": {"source": "anomaly"}}

    def _snapshot(self, **anomaly):
        a = {"metric": "error_count_15m", "value": 40.0, "baseline_mean": 2.0,
             "z_score": 7.6, "severity": "critical"}
        a.update(anomaly)
        return {"anomaly": {"read": True, "anomalies": [a],
                            "parts": {"error_count_15m": "cv-mig"}}}

    def test_alert_snapshots_anomaly_classification(self):
        from src.rules.engine import _check_anomaly_rule
        sample_class = {"title": "Suspicious Activity",
                        "classification": "auth_anomaly",
                        "business_impact": "Possible credential abuse",
                        "details": [], "actions": ["Investigate"]}
        with patch("src.security.anomaly_detector.classify_anomalies",
                   return_value=sample_class):
            checked, alerts = _check_anomaly_rule(self._anomaly_rule(), self._snapshot(), {})
        assert checked == {("errors", "cv-mig")}
        assert alerts[0].anomaly_classification == sample_class
        assert alerts[0].group == "errors" and alerts[0].node_id == "cv-mig"
        assert alerts[0].severity == "critical"

    def test_message_preserves_metric_detail_not_classification_title(self):
        """REQ-004: alert.message keeps {description}: {metric}={value};
        title travels in anomaly_classification, not by overwriting message."""
        from src.rules.engine import _check_anomaly_rule
        sample_class = {"title": "Suspicious Activity", "details": [],
                        "actions": [], "business_impact": "x"}
        with patch("src.security.anomaly_detector.classify_anomalies",
                   return_value=sample_class):
            _, alerts = _check_anomaly_rule(self._anomaly_rule(), self._snapshot(), {})
        assert "error_count_15m=40.0" in alerts[0].message
        assert "Anomaly detected" in alerts[0].message
        assert alerts[0].message != "Suspicious Activity"
        assert alerts[0].anomaly_classification["title"] == "Suspicious Activity"

    def test_classify_anomalies_exception_does_not_crash_evaluate(self):
        """REQ-004: a raising classify_anomalies must not crash the rule
        evaluation — alert still produced, classification is None."""
        from src.rules.engine import _check_anomaly_rule
        with patch("src.security.anomaly_detector.classify_anomalies",
                   side_effect=RuntimeError("malformed anomaly")):
            _, alerts = _check_anomaly_rule(self._anomaly_rule(), self._snapshot(), {})
        assert alerts and alerts[0].anomaly_classification is None
        assert "error_count_15m=40.0" in alerts[0].message

    def test_non_anomaly_rule_does_not_attach_classification(self):
        """Only source=='anomaly' rules carry anomaly_classification."""
        from src.rules.engine import _check_global_rule
        rule = {"id": "errors", "severity": "warning", "description": "Errors",
                "scope": "global",
                "condition": {"source": "logging", "metric": "error_count_15m",
                              "operator": ">", "threshold": 1}}
        _, alert = _check_global_rule(rule, {"logging": {"error_count_15m": 9, "part": "p"}}, {})
        assert alert is not None
        assert alert.anomaly_classification is None

    def test_alert_to_dict_includes_anomaly_classification(self):
        """The serialized payload exposes the field so the FE can read per-alert."""
        from src.models.alert import Alert
        a = Alert(rule_id="r", severity="warning", message="m", triggered_at="t",
                  anomaly_classification={"title": "T", "classification": "c"})
        d = a.to_dict()
        assert "anomaly_classification" in d
        assert d["anomaly_classification"]["title"] == "T"


class TestEvaluateRules:
    def setup_method(self):
        _reset_module()

    @patch("src.rules.engine.load_rules")
    def test_returns_alerts_on_violation(self, mock_load):
        from src.rules.engine import evaluate_rules
        mock_load.return_value = [
            {"id": "ram_high", "severity": "warning", "description": "High RAM",
             "scope": "node", "node_types": ["vm"],
             "condition": {"metric": "ram_percent", "operator": ">", "threshold": 85}}
        ]
        nodes = [Node(id="vm-1", label="VM", type="vm", status="healthy",
                      metrics={"ram_percent": 92.0})]
        alerts = evaluate_rules(nodes, {}, rules_path="dummy.yaml")
        assert len(alerts) == 1
        assert alerts[0].rule_id == "ram_high"

    @patch("src.rules.engine.load_rules")
    def test_returns_empty_when_healthy(self, mock_load):
        from src.rules.engine import evaluate_rules
        mock_load.return_value = [
            {"id": "ram_high", "severity": "warning",
             "scope": "node", "node_types": ["vm"],
             "condition": {"metric": "ram_percent", "operator": ">", "threshold": 85}}
        ]
        nodes = [Node(id="vm-1", label="VM", type="vm", status="healthy",
                      metrics={"ram_percent": 50.0})]
        alerts = evaluate_rules(nodes, {}, rules_path="dummy.yaml")
        assert len(alerts) == 0

    @patch("src.rules.engine.load_rules")
    def test_deduplication_within_window(self, mock_load):
        from src.rules.engine import evaluate_rules
        mock_load.return_value = [
            {"id": "ram_high", "severity": "warning", "description": "High RAM",
             "scope": "node", "node_types": ["vm"],
             "condition": {"metric": "ram_percent", "operator": ">", "threshold": 85}}
        ]
        nodes = [Node(id="vm-1", label="VM", type="vm", status="healthy",
                      metrics={"ram_percent": 92.0})]
        # First evaluation: 1 new alert
        alerts1 = evaluate_rules(nodes, {}, rules_path="dummy.yaml")
        assert len(alerts1) == 1
        # Second evaluation: same alert still in store, no new one added
        alerts2 = evaluate_rules(nodes, {}, rules_path="dummy.yaml")
        assert len(alerts2) == 1  # store still has 1, not 2

    @patch("src.rules.engine.load_rules")
    def test_global_and_node_rules_together(self, mock_load):
        from src.rules.engine import evaluate_rules
        mock_load.return_value = [
            {"id": "ram_high", "severity": "warning", "description": "High RAM",
             "scope": "node", "node_types": ["vm"],
             "condition": {"metric": "ram_percent", "operator": ">", "threshold": 85}},
            {"id": "error_spike", "severity": "warning", "description": "Errors",
             "scope": "global",
             "condition": {"source": "logging", "metric": "error_count_15m",
                           "operator": ">", "threshold": 5}},
        ]
        nodes = [Node(id="vm-1", label="VM", type="vm", status="healthy",
                      metrics={"ram_percent": 92.0})]
        snapshot = {"logging": {"error_count_15m": 10, "part": "vm-1"}}
        alerts = evaluate_rules(nodes, snapshot, rules_path="dummy.yaml")
        assert len(alerts) == 2
        rule_ids = {a.rule_id for a in alerts}
        assert "ram_high" in rule_ids
        assert "error_spike" in rule_ids


class TestGetAlerts:
    def setup_method(self):
        _reset_module()

    @patch("src.rules.engine.load_rules")
    def test_returns_alert_dicts(self, mock_load):
        from src.rules.engine import evaluate_rules, get_alerts
        mock_load.return_value = [
            {"id": "node_error", "severity": "critical", "description": "Error",
             "scope": "node",
             "condition": {"metric": "status", "operator": "==", "value": "error"}}
        ]
        nodes = [Node(id="vm-1", label="VM", type="vm", status="error")]
        evaluate_rules(nodes, {}, rules_path="dummy.yaml")
        alerts = get_alerts()
        assert len(alerts) == 1
        assert isinstance(alerts[0], dict)
        assert alerts[0]["rule_id"] == "node_error"
        assert alerts[0]["severity"] == "critical"


class TestAuditLog:
    def setup_method(self):
        _reset_module()

    @patch("src.rules.engine.load_rules")
    def test_audit_log_records_evaluation(self, mock_load):
        from src.rules.engine import evaluate_rules, get_audit_log
        mock_load.return_value = [
            {"id": "ram_high", "severity": "warning", "description": "High RAM",
             "scope": "node", "node_types": ["vm"],
             "condition": {"metric": "ram_percent", "operator": ">", "threshold": 85}}
        ]
        nodes = [Node(id="vm-1", label="VM", type="vm", status="healthy",
                      metrics={"ram_percent": 92.0})]
        evaluate_rules(nodes, {}, rules_path="dummy.yaml")
        log = get_audit_log()
        assert len(log) == 1
        entry = log[0]
        assert entry["rules_evaluated"] == 1
        assert entry["nodes_checked"] == 1
        assert entry["alerts_new"] == 1
        assert "timestamp" in entry
        assert len(entry["triggered"]) == 1
        assert entry["triggered"][0]["rule_id"] == "ram_high"

    @patch("src.rules.engine.load_rules")
    def test_audit_log_records_clean_evaluation(self, mock_load):
        from src.rules.engine import evaluate_rules, get_audit_log
        mock_load.return_value = [
            {"id": "ram_high", "severity": "warning",
             "scope": "node", "node_types": ["vm"],
             "condition": {"metric": "ram_percent", "operator": ">", "threshold": 85}}
        ]
        nodes = [Node(id="vm-1", label="VM", type="vm", status="healthy",
                      metrics={"ram_percent": 50.0})]
        evaluate_rules(nodes, {}, rules_path="dummy.yaml")
        log = get_audit_log()
        assert len(log) == 1
        assert log[0]["alerts_new"] == 0
        assert log[0]["triggered"] == []

    @patch("src.rules.engine.load_rules")
    def test_audit_log_most_recent_first(self, mock_load):
        from src.rules.engine import evaluate_rules, get_audit_log
        mock_load.return_value = [
            {"id": "ram_high", "severity": "warning", "description": "High RAM",
             "scope": "node", "node_types": ["vm"],
             "condition": {"metric": "ram_percent", "operator": ">", "threshold": 85}}
        ]
        # First eval: healthy
        nodes_ok = [Node(id="vm-1", label="VM", type="vm", status="healthy",
                         metrics={"ram_percent": 50.0})]
        evaluate_rules(nodes_ok, {}, rules_path="dummy.yaml")
        # Second eval: breach
        nodes_bad = [Node(id="vm-2", label="VM2", type="vm", status="healthy",
                          metrics={"ram_percent": 95.0})]
        evaluate_rules(nodes_bad, {}, rules_path="dummy.yaml")
        log = get_audit_log()
        assert len(log) == 2
        # Most recent first
        assert log[0]["alerts_new"] == 1
        assert log[1]["alerts_new"] == 0


class TestAcknowledgeAlert:
    def setup_method(self):
        _reset_module()

    @patch("src.rules.engine.load_rules")
    def test_acknowledge_existing_alert(self, mock_load):
        from src.rules.engine import evaluate_rules, acknowledge_alert, get_alerts
        mock_load.return_value = [
            {"id": "ram_high", "severity": "warning", "description": "High RAM",
             "scope": "node", "node_types": ["vm"],
             "condition": {"metric": "ram_percent", "operator": ">", "threshold": 85}}
        ]
        nodes = [Node(id="vm-1", label="VM", type="vm", status="healthy",
                      metrics={"ram_percent": 92.0})]
        evaluate_rules(nodes, {}, rules_path="dummy.yaml")
        result = acknowledge_alert("ram_high", "vm-1", "operator@example.com")
        assert result is True
        alerts = get_alerts()
        assert alerts[0]["acknowledged"] is True
        assert alerts[0]["acknowledged_by"] == "operator@example.com"
        assert alerts[0]["acknowledged_at"] is not None

    @patch("src.rules.engine.load_rules")
    def test_acknowledge_nonexistent_alert(self, mock_load):
        from src.rules.engine import evaluate_rules, acknowledge_alert
        mock_load.return_value = []
        evaluate_rules([], {}, rules_path="dummy.yaml")
        result = acknowledge_alert("no_such_rule", None, "user")
        assert result is False

    @patch("src.rules.engine.load_rules")
    def test_double_acknowledge_returns_false(self, mock_load):
        from src.rules.engine import evaluate_rules, acknowledge_alert
        mock_load.return_value = [
            {"id": "node_error", "severity": "critical", "description": "Error",
             "scope": "node",
             "condition": {"metric": "status", "operator": "==", "value": "error"}}
        ]
        nodes = [Node(id="vm-1", label="VM", type="vm", status="error")]
        evaluate_rules(nodes, {}, rules_path="dummy.yaml")
        assert acknowledge_alert("node_error", "vm-1", "user1") is True
        assert acknowledge_alert("node_error", "vm-1", "user2") is False

    @patch("src.rules.engine.load_rules")
    def test_acknowledge_logged_in_audit_trail(self, mock_load):
        from src.rules.engine import evaluate_rules, acknowledge_alert, get_audit_log
        mock_load.return_value = [
            {"id": "ram_high", "severity": "warning", "description": "High RAM",
             "scope": "node", "node_types": ["vm"],
             "condition": {"metric": "ram_percent", "operator": ">", "threshold": 85}}
        ]
        nodes = [Node(id="vm-1", label="VM", type="vm", status="healthy",
                      metrics={"ram_percent": 92.0})]
        evaluate_rules(nodes, {}, rules_path="dummy.yaml")
        acknowledge_alert("ram_high", "vm-1", "auditor@pharma.com")
        log = get_audit_log()
        # Most recent entry is the ack
        ack_entry = log[0]
        assert ack_entry["action"] == "acknowledge"
        assert ack_entry["rule_id"] == "ram_high"
        assert ack_entry["acknowledged_by"] == "auditor@pharma.com"
