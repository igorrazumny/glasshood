# File: tests/test_landscape_alarms.py
# Purpose: REQ-GHA-028 — each system's alarms come from its landscape file; sure alarms
# first, the rest marked as examples; response time is the typical (median) request

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

import src.collectors.coldvault as cv
import src.rules.engine as eng
from src.collectors import alarm_sources
from src.collectors.gcp_monitoring import _bucket_bounds, median_from_buckets
from src.models.topology import Node

SITE = {"id": "site_unreachable", "name": "Site reachable", "group": "site",
        "title": "{part}: coldvault.ai is not answering", "severity": "critical",
        "scope": "global", "part": "cv-public",
        "condition": {"source": "coldvault", "metric": "site_unreachable", "operator": ">", "threshold": 0}}
MEMORY = {"id": "memory_high", "name": "Memory use", "group": "ram",
          "title": "{part}: memory is {value}% full", "severity": "warning",
          "scope": "global", "part": "cv-mig",
          "condition": {"source": "coldvault", "metric": "ram_used_percent", "operator": ">", "threshold": 85}}
ANOMALY = {"id": "anomaly_detected", "name": "Unusual readings", "kind": "example",
           "title": "{part}: {what} is unusual", "severity": "warning", "scope": "global",
           "per_anomaly": True, "groups": {"error_count_15m": "errors"},
           "condition": {"source": "anomaly"}}
ERRORS = {"id": "error_spike", "name": "Application errors", "group": "errors",
          "title": "{part}: {value} errors", "severity": "warning", "scope": "global",
          "condition": {"source": "logging", "metric": "error_count_15m", "operator": ">", "threshold": 5}}

PUBLIC = Node(id="cv-public", label="Visitor → coldvault.ai", type="infra", status="healthy")
MIG = Node(id="cv-mig", label="Confidential VM (MIG)", type="infra", status="healthy")


@pytest.fixture(autouse=True)
def _reset():
    for s in (eng._active, eng._resolved, eng._rule_checked_at, eng._rule_names, eng._audit_log):
        s.clear()
    yield


def _manifest(tmp_path, env_body: str) -> Path:
    d = tmp_path / "manifests"
    d.mkdir()
    (d / "cv.yaml").write_text("environments:\n- environment: prod\n" + env_body)
    return d


def _eval_landscape(rules, nodes, snap):
    with patch.object(alarm_sources, "alarms", return_value=rules):
        return eng.evaluate_rules(nodes, snap)


class TestDefinedInTheLandscape:
    def test_alarms_are_read_from_the_landscape_file(self, tmp_path):
        d = tmp_path / "manifests"
        d.mkdir()
        (d / "cv.yaml").write_text(yaml.safe_dump(
            {"environments": [{"environment": "prod", "alarms": [SITE, MEMORY]}]}))
        with patch.object(alarm_sources, "_manifest_dir", return_value=d):
            assert [r["id"] for r in alarm_sources.alarms()] == ["site_unreachable", "memory_high"]

    def test_no_declaration_means_the_general_defaults(self, tmp_path):
        d = _manifest(tmp_path, "  nodes: []\n")
        with patch.object(alarm_sources, "_manifest_dir", return_value=d):
            assert alarm_sources.alarms() is None
        with patch.object(alarm_sources, "alarms", return_value=None), \
                patch.object(eng, "load_rules", return_value=[MEMORY]) as lr:
            eng.evaluate_rules([MIG], {})
        lr.assert_called_once()

    def test_invalid_entries_are_left_out(self, tmp_path):
        d = _manifest(tmp_path, "  alarms:\n  - {id: x}\n  - just text\n  - {id: ok, condition: {source: coldvault}}\n")
        with patch.object(alarm_sources, "_manifest_dir", return_value=d):
            assert [r["id"] for r in alarm_sources.alarms()] == ["ok"]

    def test_landscape_alarms_replace_the_defaults(self):
        with patch.object(alarm_sources, "alarms", return_value=[SITE]), \
                patch.object(eng, "load_rules") as lr:
            alerts = eng.evaluate_rules([PUBLIC], {"coldvault": {"site_unreachable": 1}})
        lr.assert_not_called()
        assert alerts[0].title == "Visitor → coldvault.ai: coldvault.ai is not answering"
        assert alerts[0].severity == "critical" and alerts[0].kind == "alarm"

    def test_changing_the_threshold_in_the_landscape_changes_the_alarm(self):
        snap = {"coldvault": {"ram_used_percent": 80}}
        assert _eval_landscape([MEMORY], [MIG], snap) == []
        lower = {**MEMORY, "condition": {**MEMORY["condition"], "threshold": 75}}
        alerts = _eval_landscape([lower], [MIG], snap)
        assert len(alerts) == 1 and alerts[0].title == "Confidential VM (MIG): memory is 80% full"


class TestSureAlarms:
    def test_site_reachable_clears_and_unknown_is_not_checked(self):
        assert len(_eval_landscape([SITE], [PUBLIC], {"coldvault": {"site_unreachable": 1}})) == 1
        assert _eval_landscape([SITE], [PUBLIC], {"coldvault": {"site_unreachable": 0}}) == []
        eng._rule_checked_at.clear()
        _eval_landscape([SITE], [PUBLIC], {"coldvault": {"site_unreachable": None}})
        assert {r["id"]: r["checked"] for r in eng.get_rule_status()}["site_unreachable"] is False

    def test_alarm_data_from_the_collector(self):
        with patch.object(cv, "_health", {"status": "unreachable"}), \
                patch.object(cv, "_metrics", {"error": "x"}), \
                patch.object(cv, "_metrics_status", {"read": False}), \
                patch.object(cv, "_last_read_ok", 1000.0):
            d = cv.alarm_data(now=1000.0 + 45 * 60)
        assert d == {"site_unreachable": 1, "ram_used_percent": None,
                     "disk_used_percent": None, "minutes_since_reading": 45.0}
        with patch.object(cv, "_health", {"status": "healthy"}), \
                patch.object(cv, "_metrics", {"system": {"ram_used_percent": 21.3, "disk_used_percent": 40}}), \
                patch.object(cv, "_metrics_status", {"read": True}), \
                patch.object(cv, "_last_read_ok", 1000.0):
            d = cv.alarm_data(now=1060.0)
        assert d["site_unreachable"] == 0 and d["ram_used_percent"] == 21.3 and d["minutes_since_reading"] == 1.0
        with patch.object(cv, "_health", {}):
            assert cv.alarm_data()["site_unreachable"] is None  # not polled yet: not checked

    def test_vm_status_is_not_a_second_alarm_for_the_site(self):
        node_error = {"id": "node_error", "name": "Part failing its check", "group": "status",
                      "title": "{part} is failing its check", "severity": "critical", "scope": "node",
                      "exclude_node_types": ["vm"],
                      "condition": {"metric": "status", "operator": "==", "value": "error"}}
        vm = Node(id="vm-1", label="VM", type="vm", status="error")
        sql = Node(id="cv-sql", label="Cloud SQL", type="infra", status="error")
        alerts = _eval_landscape([node_error], [vm, sql], {})
        assert [a.node_id for a in alerts] == ["cv-sql"]


class TestExamples:
    def test_example_is_marked_and_at_most_a_warning(self):
        anomaly = {"metric": "error_count_15m", "value": 40.0, "baseline_mean": 1.0,
                   "z_score": 9, "severity": "critical"}
        snap = {"anomaly": {"read": True, "anomalies": [anomaly], "parts": {"error_count_15m": "cv-mig"}}}
        alerts = _eval_landscape([ANOMALY], [MIG], snap)
        assert alerts[0].severity == "warning" and alerts[0].to_dict()["kind"] == "example"

    def test_real_alarm_wins_over_an_example_on_the_same_event(self):
        anomaly = {"metric": "error_count_15m", "value": 8.0, "baseline_mean": 1.0,
                   "z_score": 4, "severity": "warning"}
        snap = {"logging": {"error_count_15m": 8, "part": "cv-mig"},
                "anomaly": {"read": True, "anomalies": [anomaly], "parts": {"error_count_15m": "cv-mig"}}}
        for order in ([ANOMALY, ERRORS], [ERRORS, ANOMALY]):
            eng._active.clear()
            alerts = _eval_landscape(order, [MIG], snap)
            assert len(alerts) == 1 and alerts[0].kind == "alarm" and alerts[0].rule_id == "error_spike"

    def test_findings_are_observations(self):
        eng.track_findings([{"id": "dup", "text": "29 identical alert policies", "part": "cv-mig",
                             "active": True}], [MIG])
        assert eng.get_alerts()[0]["kind"] == "observation"

    def test_default_rules_mark_unusual_readings_and_cpu_as_examples(self):
        rules = {r["id"]: r for r in eng.load_rules("config/rules.yaml")}
        assert rules["anomaly_detected"]["kind"] == "example"
        assert rules["cpu_high"]["kind"] == "example"
        assert "typical" in rules["lb_latency_high"]["title"]


class TestTypicalResponseTime:
    def test_one_long_chat_answer_does_not_move_the_median(self):
        # 100 requests of ~120 ms and one of 83 s: the mean would be ~940 ms
        bounds = _bucket_bounds("explicit_buckets", {"bounds": [100, 150, 1000, 100000]}, 5)
        counts = {bounds[1]: 100, bounds[3]: 1}
        median = median_from_buckets(counts)
        assert 100 <= median <= 150

    def test_slow_service_is_still_slow(self):
        bounds = _bucket_bounds("explicit_buckets", {"bounds": [100, 1000, 8000]}, 4)
        assert median_from_buckets({bounds[0]: 10, bounds[2]: 90}) > 1000

    def test_bucket_bounds(self):
        b = _bucket_bounds("exponential_buckets", {"num_finite_buckets": 2, "growth_factor": 2, "scale": 1}, 4)
        assert b == [(float("-inf"), 1), (1, 2), (2, 4), (4, float("inf"))]
        b = _bucket_bounds("linear_buckets", {"num_finite_buckets": 1, "width": 10, "offset": 0}, 2)
        assert b == [(float("-inf"), 0), (0, 10)]  # trailing empty buckets may be omitted

    def test_no_requests_is_no_reading(self):
        assert median_from_buckets({}) is None
        assert median_from_buckets({(0, 10): 0}) is None


class TestReviewOfLiveRollout:
    """Found on the live rollout of REQ-GHA-028 (2026-11-06)."""

    def test_buckets_of_the_raw_protobuf_distribution_are_read(self):
        # list_time_series returns google.api.Distribution (raw protobuf), not proto-plus
        from google.api import distribution_pb2 as dp
        from google.cloud.monitoring_v3.types import Point, TypedValue
        from src.collectors.gcp_monitoring import _options
        opts = dp.Distribution.BucketOptions(explicit_buckets=dp.Distribution.BucketOptions.Explicit(
            bounds=[100, 150, 1000, 100000]))
        p = Point(value=TypedValue(distribution_value=dp.Distribution(
            count=101, bucket_options=opts, bucket_counts=[0, 100, 0, 1])))
        d = p.value.distribution_value
        kind, params = _options(d.bucket_options)
        b = _bucket_bounds(kind, params, len(d.bucket_counts))
        assert 100 <= median_from_buckets(dict(zip(b, d.bucket_counts))) <= 150

    def test_not_checked_lists_only_the_rules_in_force(self):
        with patch.object(alarm_sources, "alarms", return_value=None), \
                patch.object(eng, "load_rules", return_value=[MEMORY, ERRORS]):
            eng.evaluate_rules([MIG], {})
        _eval_landscape([SITE], [PUBLIC], {"coldvault": {"site_unreachable": 0}})
        assert [r["id"] for r in eng.get_rule_status()] == ["site_unreachable"]

    def test_poll_once_reads_the_median_from_real_monitoring_messages(self):
        """neo-shadow1 review of PR #65 (C1): through poll_once, with real message types."""
        import asyncio
        import google.cloud.monitoring_v3 as mv3
        import src.collectors.gcp_monitoring as gm
        from google.cloud.monitoring_v3.types import Point, TimeSeries

        series = TimeSeries({"points": [Point({"value": {"distribution_value": {
            "count": 101,
            "bucket_options": {"explicit_buckets": {"bounds": [100, 150, 1000, 100000]}},
            "bucket_counts": [0, 100, 0, 1]}}})]})

        class Client:
            def list_time_series(self, request):
                return [series] if "backend_latencies" in request.filter else []

        sources = {"load_balancer": {"part": "cv-backend", "project": "p", "filter": "x"}}
        with patch.object(mv3, "MetricServiceClient", Client), \
                patch.object(gm.alarm_sources, "load", return_value=sources), \
                patch("src.security.anomaly_detector.judge_fresh_readings"):
            asyncio.run(gm.poll_once())
        assert 100 <= gm.get_stats()["lb_latency_ms"] <= 150
