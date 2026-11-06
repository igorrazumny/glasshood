# File: tests/test_anomaly_detector.py
# Purpose: Tests for statistical anomaly detection engine

import math
from unittest.mock import patch

from src.security.anomaly_detector import BaselineTracker


def _reset_module():
    """Reset module globals between tests."""
    import src.security.anomaly_detector as mod
    mod._anomalies = []
    mod._tracker = BaselineTracker()
    mod._audit_log.clear()
    mod._judged.clear()


class TestBaselineTracker:
    def test_update_and_stats(self):
        tracker = BaselineTracker()
        for v in [10, 12, 11, 13, 10]:
            tracker.update("test_metric", v)
        stats = tracker.get_stats("test_metric")
        assert stats["count"] == 5
        assert abs(stats["mean"] - 11.2) < 0.01

    def test_stddev_calculation(self):
        tracker = BaselineTracker()
        values = [10, 10, 10, 10, 10]
        for v in values:
            tracker.update("steady", v)
        stats = tracker.get_stats("steady")
        assert stats["stddev"] == 0.0

    def test_anomalous_spike(self):
        tracker = BaselineTracker(min_points=5)
        # Build baseline: values around 10
        for v in [10, 11, 10, 9, 10, 11, 10, 9, 10, 11]:
            tracker.update("metric", v)
        # Spike to 50 — should be anomalous
        is_anomaly, z_score = tracker.is_anomalous("metric", 50.0, sigma=3.0)
        assert is_anomaly is True
        assert z_score > 3.0

    def test_normal_value_not_anomalous(self):
        tracker = BaselineTracker(min_points=5)
        for v in [10, 11, 10, 9, 10, 11, 10, 9, 10, 11]:
            tracker.update("metric", v)
        is_anomaly, z_score = tracker.is_anomalous("metric", 10.5, sigma=3.0)
        assert is_anomaly is False

    def test_insufficient_data_not_anomalous(self):
        tracker = BaselineTracker(min_points=5)
        tracker.update("metric", 10)
        tracker.update("metric", 11)
        # Only 2 data points, need 5
        is_anomaly, z_score = tracker.is_anomalous("metric", 100.0, sigma=3.0)
        assert is_anomaly is False
        assert z_score == 0.0

    def test_zero_stddev_not_anomalous(self):
        tracker = BaselineTracker(min_points=3)
        for _ in range(5):
            tracker.update("constant", 42.0)
        is_anomaly, z_score = tracker.is_anomalous("constant", 42.0, sigma=3.0)
        assert is_anomaly is False

    def test_window_size_limits_data(self):
        tracker = BaselineTracker(window_size=5)
        for v in range(20):
            tracker.update("m", float(v))
        stats = tracker.get_stats("m")
        assert stats["count"] == 5  # only last 5

    def test_all_baselines(self):
        tracker = BaselineTracker()
        tracker.update("a", 1.0)
        tracker.update("b", 2.0)
        baselines = tracker.all_baselines()
        assert "a" in baselines
        assert "b" in baselines

    def test_unknown_metric_stats(self):
        tracker = BaselineTracker()
        stats = tracker.get_stats("nonexistent")
        assert stats["count"] == 0
        assert stats["mean"] == 0.0


class TestDetectAnomalies:
    def setup_method(self):
        _reset_module()

    @patch("src.security.anomaly_detector._load_config")
    def test_detects_spike(self, mock_config):
        from src.security.anomaly_detector import update_baselines, detect_anomalies
        mock_config.return_value = {"enabled": True, "min_data_points": 5,
                                    "metrics": {"error_count_15m": {"min_change": 5}}}
        monitoring = {"lb_latency_ms": 100, "lb_request_count_1h": 500, "vm_cpu_percent": 30}
        logging_stats = {"error_count_15m": 2}
        # Build baseline with normal values
        for _ in range(10):
            update_baselines(monitoring, logging_stats)
        # Now spike error count
        spike_logging = {"error_count_15m": 200}
        anomalies = detect_anomalies(monitoring, spike_logging, {})
        assert len(anomalies) >= 1
        error_anomaly = next(a for a in anomalies if a["metric"] == "error_count_15m")
        assert error_anomaly["value"] == 200
        assert error_anomaly["z_score"] > 3.0

    @patch("src.security.anomaly_detector._load_config")
    def test_normal_values_no_anomaly(self, mock_config):
        from src.security.anomaly_detector import update_baselines, detect_anomalies
        mock_config.return_value = {"enabled": True, "metrics": {}, "min_data_points": 5}
        monitoring = {"lb_latency_ms": 100, "vm_cpu_percent": 30}
        logging_stats = {"error_count_15m": 2}
        for _ in range(10):
            update_baselines(monitoring, logging_stats)
        anomalies = detect_anomalies(monitoring, logging_stats, {})
        assert len(anomalies) == 0

    @patch("src.security.anomaly_detector._load_config")
    def test_handles_missing_metrics(self, mock_config):
        from src.security.anomaly_detector import detect_anomalies
        mock_config.return_value = {"enabled": True, "metrics": {}, "min_data_points": 5}
        anomalies = detect_anomalies({}, {}, {})
        assert anomalies == []

    @patch("src.security.anomaly_detector._load_config")
    def test_disabled_returns_empty(self, mock_config):
        from src.security.anomaly_detector import detect_anomalies
        mock_config.return_value = {"enabled": False}
        anomalies = detect_anomalies({"lb_latency_ms": 99999}, {"error_count_15m": 99999}, {})
        assert anomalies == []


class TestFallbackThresholds:
    def setup_method(self):
        _reset_module()

    @patch("src.security.anomaly_detector._load_config")
    def test_fallback_on_warmup(self, mock_config):
        from src.security.anomaly_detector import detect_anomalies
        mock_config.return_value = {
            "enabled": True,
            "min_data_points": 5,
            "metrics": {
                "error_count_15m": {"sigma": 3.0, "fallback_threshold": 15},
            },
        }
        # No baseline data — should use fallback threshold of 15
        logging_stats = {"error_count_15m": 20}
        anomalies = detect_anomalies({}, logging_stats, {})
        assert len(anomalies) == 1
        assert anomalies[0]["metric"] == "error_count_15m"

    @patch("src.security.anomaly_detector._load_config")
    def test_no_fallback_below_threshold(self, mock_config):
        from src.security.anomaly_detector import detect_anomalies
        mock_config.return_value = {
            "enabled": True,
            "min_data_points": 5,
            "metrics": {
                "error_count_15m": {"sigma": 3.0, "fallback_threshold": 15},
            },
        }
        logging_stats = {"error_count_15m": 10}  # below 15 threshold
        anomalies = detect_anomalies({}, logging_stats, {})
        assert len(anomalies) == 0


class TestGetAnomalies:
    def setup_method(self):
        _reset_module()

    def test_empty_by_default(self):
        from src.security.anomaly_detector import get_anomalies
        assert get_anomalies() == []

    def test_get_stats(self):
        from src.security.anomaly_detector import get_stats
        stats = get_stats()
        assert stats["anomaly_count"] == 0
        assert stats["high_confidence_count"] == 0


_CONFIG = {
    "enabled": True, "min_data_points": 5, "window_seconds": 3600,
    "metrics": {"error_count_15m": {"sigma": 3.0, "min_change": 5, "fallback_threshold": 15},
                "lb_latency_ms": {"sigma": 2.5, "min_change": 200, "fallback_threshold": 2000}},
}


def _feed(values, start=1000.0, step=600.0, metric_key="error_count_15m"):
    """Run one detection per fresh reading, readings `step` seconds apart. Returns the last result."""
    from src.security.anomaly_detector import detect_anomalies
    result = []
    for i, v in enumerate(values):
        result = detect_anomalies({}, {metric_key: v, "read_at": start + i * step}, {})
    return result


class TestFreshReadings:
    """REQ-GHA-026: the baseline follows collector readings, not page views."""

    def setup_method(self):
        _reset_module()

    @patch("src.security.anomaly_detector._load_config", return_value=_CONFIG)
    def test_repeated_views_of_one_reading_add_nothing(self, _):
        import src.security.anomaly_detector as mod
        _feed([2, 3, 2])
        before = mod._tracker.get_stats("error_count_15m")["count"]
        for _ in range(50):
            mod.detect_anomalies({}, {"error_count_15m": 2, "read_at": 1000.0 + 2 * 600}, {})
        assert mod._tracker.get_stats("error_count_15m")["count"] == before == 3

    @patch("src.security.anomaly_detector._load_config", return_value=_CONFIG)
    def test_verdict_does_not_depend_on_view_count(self, _):
        import src.security.anomaly_detector as mod
        _feed([2, 3, 2, 3, 2, 3])
        spike = {"error_count_15m": 200, "read_at": 1000.0 + 6 * 600}
        first = mod.detect_anomalies({}, spike, {})
        again = [mod.detect_anomalies({}, spike, {}) for _ in range(20)]
        assert first and first[0]["severity"] == "critical"
        assert all(r == first for r in again)
        assert mod.get_stats()["anomaly_count"] == 1

    @patch("src.security.anomaly_detector._load_config", return_value=_CONFIG)
    def test_reading_judged_against_baseline_without_it(self, _):
        import src.security.anomaly_detector as mod
        _feed([2, 3, 2, 3, 2, 3])
        result = mod.detect_anomalies({}, {"error_count_15m": 200, "read_at": 1000.0 + 6 * 600}, {})
        assert result[0]["baseline_mean"] == 2.5
        assert mod._tracker.get_stats("error_count_15m")["count"] == 7

    @patch("src.security.anomaly_detector._load_config", return_value=_CONFIG)
    def test_failed_poll_is_not_a_new_reading(self, _):
        import src.security.anomaly_detector as mod
        _feed([2, 3, 2])
        # A failed poll changes last_poll but not read_at
        for poll in range(5):
            mod.detect_anomalies({}, {"error_count_15m": 2, "read_at": 2200.0, "last_poll": 3000.0 + poll}, {})
        assert mod._tracker.get_stats("error_count_15m")["count"] == 3

    @patch("src.security.anomaly_detector._load_config", return_value=_CONFIG)
    def test_baseline_covers_configured_time_span(self, _):
        import src.security.anomaly_detector as mod
        # 30 readings ten minutes apart = five hours; only the last hour stays
        _feed([2] * 30)
        assert mod._tracker.get_stats("error_count_15m")["count"] == 7  # 0..60 min inclusive

    def test_time_window_drops_old_points(self):
        tracker = BaselineTracker(window_seconds=100)
        for ts in range(0, 1000, 10):
            tracker.update("m", 1.0, ts=float(ts))
        assert tracker.get_stats("m")["count"] == 11


class TestFlatBaseline:
    """REQ-GHA-026: a flat baseline does not turn a small step into a critical alert."""

    def setup_method(self):
        _reset_module()

    @patch("src.security.anomaly_detector._load_config", return_value=_CONFIG)
    def test_one_error_after_zero_errors_is_not_critical(self, _):
        result = _feed([0, 0, 0, 0, 0, 0, 1])
        assert not any(a["severity"] == "critical" for a in result)

    @patch("src.security.anomaly_detector._load_config", return_value=_CONFIG)
    def test_change_below_min_change_never_counts(self, _):
        assert _feed([0, 0, 0, 0, 0, 0, 4]) == []

    @patch("src.security.anomaly_detector._load_config", return_value=_CONFIG)
    def test_large_jump_from_flat_baseline_still_alerts(self, _):
        result = _feed([0, 0, 0, 0, 0, 0, 200])
        assert result and result[0]["severity"] == "critical"
        assert math.isfinite(result[0]["z_score"])

    @patch("src.security.anomaly_detector._load_config")
    def test_flat_baseline_without_min_change_is_at_most_warning(self, mock_config):
        mock_config.return_value = {"enabled": True, "min_data_points": 5, "metrics": {}}
        result = _feed([0, 0, 0, 0, 0, 0, 1])
        assert result and all(a["severity"] == "warning" for a in result)

    def test_tracker_flat_baseline_gives_finite_z(self):
        tracker = BaselineTracker(min_points=3)
        for _ in range(5):
            tracker.update("constant", 0.0)
        is_anomaly, z = tracker.is_anomalous("constant", 1.0, sigma=3.0, min_change=5)
        assert is_anomaly is False and math.isfinite(z)


class TestClassifyNeverFails:
    """REQ-GHA-026: the plain-language explanation never fails."""

    def test_value_zero_against_positive_baseline(self):
        from src.security.anomaly_detector import classify_anomalies
        out = classify_anomalies([{"metric": "lb_request_count_1h", "value": 0.0,
                                   "baseline_mean": 500.0, "z_score": -4.2, "confidence": 0.84}])
        assert "dropped to 0" in out["details"][0]["summary"]

    def test_flat_zero_baseline(self):
        from src.security.anomaly_detector import classify_anomalies
        out = classify_anomalies([{"metric": "error_count_15m", "value": 1.0,
                                   "baseline_mean": 0.0, "z_score": 0.0, "confidence": 0.5}])
        assert out["details"][0]["summary"]


class TestCollectorReadAt:
    """REQ-GHA-026: only a successful collector poll is a fresh reading."""

    def test_failed_logging_poll_keeps_read_at(self):
        import asyncio
        import sys
        import types
        import src.collectors.gcp_logging as gl
        broken = types.ModuleType("google.cloud.logging_v2")

        def _client(**_):
            raise RuntimeError("logging unavailable")
        broken.Client = _client
        gl._stats = {"error_count_15m": 3, "recent_errors": [], "last_poll": 1.0, "read_at": 1.0}
        source = {"errors": {"part": "cv-mig", "project": "p", "filter": "x"}}
        with patch.dict(sys.modules, {"google.cloud.logging_v2": broken}), \
                patch.object(gl.alarm_sources, "load", return_value=source):
            asyncio.run(gl.poll_once())
        assert gl._stats["read_at"] == 1.0
        assert gl._stats["last_poll"] > 1.0


class TestReviewFixes:
    """neo-shadow1 review of REQ-GHA-026 (C1, C2)."""

    def setup_method(self):
        _reset_module()

    @patch("src.security.anomaly_detector._load_config", return_value=_CONFIG)
    def test_expired_points_are_not_the_baseline_of_a_late_reading(self, _):
        # C1: six readings, then one a long time later: no warmed baseline remains
        import src.security.anomaly_detector as mod
        _feed([2, 3, 2, 3, 2, 3])
        late = mod.detect_anomalies({}, {"error_count_15m": 200, "read_at": 10000.0}, {})
        assert all(a["severity"] != "critical" for a in late)  # fallback warning at most
        assert mod._tracker.get_stats("error_count_15m")["count"] == 1

    def test_readings_are_judged_by_the_collector_not_by_views(self):
        # C2: every successful collector reading is judged, whether or not anyone views
        import src.collectors.gcp_logging as gl
        import src.security.anomaly_detector as mod
        calls = []
        with patch.object(mod, "detect_anomalies", side_effect=lambda *a: calls.append(a) or []), \
                patch("src.config.settings.ANOMALY_DETECTION_ENABLED", True):
            mod.judge_fresh_readings()
        assert len(calls) == 1

    def test_topology_view_does_not_judge(self):
        import inspect
        import src.api.routes.topology as topo
        src_text = inspect.getsource(topo._build_topology)
        assert "detect_anomalies(" not in src_text and "get_anomalies()" in src_text
