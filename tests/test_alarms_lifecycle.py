# File: tests/test_alarms_lifecycle.py
# Purpose: REQ-GHA-027 — every alarm is about the monitored system, current, and said once

import asyncio
import sys
import types
from unittest.mock import patch

import pytest

import src.rules.engine as eng
from src.models.topology import Node

RULES = [
    {"id": "error_spike", "name": "Application errors", "group": "errors", "severity": "warning",
     "description": "Error rate spike", "title": "{part}: {value} application errors in the last 15 minutes",
     "scope": "global",
     "condition": {"source": "logging", "metric": "error_count_15m", "operator": ">", "threshold": 5}},
    {"id": "error_storm", "name": "Application errors", "group": "errors", "severity": "critical",
     "description": "Error storm", "title": "{part}: many application errors ({value} in the last 15 minutes)",
     "scope": "global",
     "condition": {"source": "logging", "metric": "error_count_15m", "operator": ">", "threshold": 20}},
    {"id": "ram_high", "name": "Memory use", "group": "ram", "severity": "warning",
     "description": "High RAM usage", "title": "{part}: memory is {value}% full",
     "scope": "node", "node_types": ["vm"],
     "condition": {"metric": "ram_percent", "operator": ">", "threshold": 85}},
    {"id": "node_error", "name": "Part failing its check", "group": "status", "severity": "critical",
     "description": "Node in error state", "title": "{part} is failing its check", "scope": "node",
     "condition": {"metric": "status", "operator": "==", "value": "error"}},
    {"id": "anomaly_detected", "name": "Unusual readings", "severity": "warning",
     "description": "Statistical anomaly", "title": "{part}: {what} is unusual ({value}, normally about {normal})",
     "scope": "global", "per_anomaly": True, "groups": {"error_count_15m": "errors"},
     "condition": {"source": "anomaly"}},
]

APP = Node(id="cv-mig", label="Confidential VM (MIG)", type="mig", status="healthy")


def _vm(status="healthy", **metrics):
    return Node(id="vm-1", label="VM q5hm", type="vm", status=status, metrics=metrics)


def _snap(errors=None, anomalies=None):
    snap = {"logging": {"error_count_15m": errors, "part": "cv-mig"}}
    if anomalies is not None:
        snap["anomaly"] = {"read": True, "anomalies": anomalies,
                           "parts": {"error_count_15m": "cv-mig"}}
    return snap


def _eval(nodes, snap):
    with patch.object(eng, "load_rules", return_value=RULES):
        return eng.evaluate_rules(nodes, snap, rules_path="x")


@pytest.fixture(autouse=True)
def _reset():
    eng._active.clear()
    eng._resolved.clear()
    eng._rule_checked_at.clear()
    eng._rule_names.clear()
    eng._audit_log.clear()
    yield


class TestCurrentOnly:
    def test_alarm_ends_when_condition_clears(self):
        assert len(_eval([APP], _snap(errors=8))) == 1
        assert _eval([APP], _snap(errors=0)) == []
        resolved = eng.get_resolved()
        assert len(resolved) == 1
        assert resolved[0]["ended_at"] and resolved[0]["first_seen"]

    def test_unchecked_condition_neither_starts_nor_ends_an_alarm(self):
        _eval([APP], _snap(errors=8))
        # An evaluation without the error data (e.g. ingest) leaves the alarm as it is
        with patch.object(eng, "load_rules", return_value=RULES):
            eng.evaluate_rules([], {})
        assert len(eng.get_alerts()) == 1 and eng.get_resolved() == []

    def test_alarm_on_a_part_gone_from_the_canvas_ends(self):
        _eval([APP, _vm(status="error")], _snap(errors=0))
        assert [a.node_id for a in eng._active.values()] == ["vm-1"]
        _eval([APP], _snap(errors=0))  # the VM was replaced
        assert eng.get_alerts() == []
        assert eng.get_resolved()[0]["node_id"] == "vm-1"


class TestSaidOnce:
    def test_persisting_condition_is_one_entry_with_first_and_last_seen(self):
        for _ in range(30):
            alerts = _eval([APP], _snap(errors=8))
        assert len(alerts) == 1
        d = eng.get_alerts()[0]
        assert d["first_seen"] <= d["last_seen"]

    def test_warning_and_critical_on_one_event_are_one_alarm_at_the_higher_severity(self):
        alerts = _eval([APP], _snap(errors=40))
        assert len(alerts) == 1
        assert alerts[0].severity == "critical"
        assert len(alerts[0].reasons) == 2  # both rules' technical lines stay in the detail

    def test_threshold_and_anomaly_on_the_same_metric_are_one_alarm(self):
        anomaly = {"metric": "error_count_15m", "value": 40.0, "baseline_mean": 2.0,
                   "z_score": 7.6, "severity": "critical"}
        alerts = _eval([APP], _snap(errors=8, anomalies=[anomaly]))
        assert len(alerts) == 1
        assert alerts[0].severity == "critical" and alerts[0].node_id == "cv-mig"

    def test_severity_goes_down_in_place(self):
        _eval([APP], _snap(errors=40))
        first = eng.get_alerts()[0]["first_seen"]
        alerts = _eval([APP], _snap(errors=8))
        assert len(alerts) == 1 and alerts[0].severity == "warning"
        assert eng.get_alerts()[0]["first_seen"] == first


class TestPlainWordsAndParts:
    def test_title_names_the_part_without_rule_names_or_metric_equals_value(self):
        alerts = _eval([APP], _snap(errors=8))
        d = alerts[0].to_dict()
        assert d["title"] == "Confidential VM (MIG): 8 application errors in the last 15 minutes"
        assert "=" not in d["title"] and "error_spike" not in d["title"]
        assert "error_count_15m=8" in d["message"]  # technical detail kept for integrations
        assert d["part_label"] == "Confidential VM (MIG)"

    def test_findings_alarm_on_their_part_and_end_when_gone(self):
        nodes = [APP, Node(id="cv-alerts", label="Alert policies", type="ops", status="healthy")]
        f = {"id": "dup", "text": "29 identical alert policies", "source": "inventory",
             "part": "cv-alerts", "active": True}
        eng.track_findings([f], nodes)
        d = eng.get_alerts()[0]
        assert d["node_id"] == "cv-alerts" and d["title"] == "Alert policies: 29 identical alert policies"
        eng.track_findings([{**f, "active": False}], nodes)
        assert eng.get_alerts() == [] and len(eng.get_resolved()) == 1

    def test_finding_whose_check_failed_keeps_its_alarm(self):
        f = {"id": "dup", "text": "t", "part": "cv-mig", "active": True}
        eng.track_findings([f], [APP])
        eng.track_findings([], [APP])  # check could not run: absent
        assert len(eng.get_alerts()) == 1


class TestNotChecked:
    def test_rules_without_data_are_listed_as_not_checked(self):
        _eval([APP, _vm()], _snap(errors=0))
        status = {r["id"]: r["checked"] for r in eng.get_rule_status()}
        assert status["error_spike"] is True
        assert status["ram_high"] is False  # the VM has no RAM reading
        assert status["node_error"] is True

    def test_signal_without_a_part_is_not_checked_and_raises_nothing(self):
        alerts = _eval([APP], {"logging": {"error_count_15m": 50}})
        assert alerts == []
        assert {r["id"]: r["checked"] for r in eng.get_rule_status()}["error_spike"] is False


class TestScopedSources:
    def _manifest(self, tmp_path, body):
        d = tmp_path / "manifests"
        d.mkdir()
        (d / "cv.yaml").write_text(body)
        return d

    def test_sources_come_from_the_manifest_and_bad_entries_are_left_out(self, tmp_path):
        from src.collectors import alarm_sources
        d = self._manifest(tmp_path, """
environments:
- environment: prod
  alarm_sources:
    errors: {part: cv-mig, project: p, filter: 'logName="x"'}
    load_balancer: {part: cv-backend, project: p}
""")
        with patch.object(alarm_sources, "_manifest_dir", return_value=d):
            assert alarm_sources.load() == {"errors": {"part": "cv-mig", "project": "p",
                                                       "filter": 'logName="x"'}}

    def test_no_declaration_reads_nothing(self, tmp_path):
        from src.collectors import alarm_sources
        import src.collectors.gcp_logging as gl
        d = self._manifest(tmp_path, "environments:\n- environment: prod\n")
        with patch.object(alarm_sources, "_manifest_dir", return_value=d):
            asyncio.run(gl.poll_once())
        assert gl.get_stats()["error_count_15m"] is None and gl.get_stats()["part"] is None

    def test_error_count_uses_only_the_declared_filter(self):
        import src.collectors.gcp_logging as gl
        seen = {}

        class Client:
            def __init__(self, project):
                seen["project"] = project

            def list_entries(self, filter_, order_by, max_results):
                seen["filter"] = filter_
                return []
        mod = types.ModuleType("google.cloud.logging_v2")
        mod.Client = Client
        source = {"errors": {"part": "cv-mig", "project": "p1", "filter": 'jsonPayload.container.name="/coldvault"'}}
        with patch.dict(sys.modules, {"google.cloud.logging_v2": mod}), \
                patch.object(gl.alarm_sources, "load", return_value=source):
            asyncio.run(gl.poll_once())
        assert seen["project"] == "p1"
        assert seen["filter"].startswith('(jsonPayload.container.name="/coldvault") AND timestamp>=')
        assert "severity" not in seen["filter"] and "gce_instance" not in seen["filter"]
        assert gl.get_stats()["error_count_15m"] == 0 and gl.get_stats()["part"] == "cv-mig"
