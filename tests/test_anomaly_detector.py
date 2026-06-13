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
        mock_config.return_value = {"enabled": True, "metrics": {}, "min_data_points": 5}
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
