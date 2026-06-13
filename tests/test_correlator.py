# File: tests/test_correlator.py
# Purpose: Tests for operational-anomaly correlation engine

from datetime import datetime, timezone, timedelta

from src.models.alert import Alert
from src.security.correlator import correlate


def _make_alert(rule_id="ram_critical", node_id="vm-1", severity="critical",
                message="High RAM", age_seconds=0) -> Alert:
    ts = (datetime.now(timezone.utc) - timedelta(seconds=age_seconds)).isoformat()
    return Alert(rule_id=rule_id, severity=severity, message=message,
                 triggered_at=ts, node_id=node_id, metric_name="ram_percent",
                 metric_value=96.0, threshold=95.0)


def _make_anomaly(metric="error_count_15m", value=200, z_score=4.2,
                  age_seconds=0) -> dict:
    ts = (datetime.now(timezone.utc) - timedelta(seconds=age_seconds)).isoformat()
    return {
        "type": "statistical_anomaly",
        "metric": metric,
        "value": value,
        "baseline_mean": 5.0,
        "baseline_stddev": 2.0,
        "z_score": z_score,
        "confidence": 0.84,
        "severity": "critical",
        "timestamp": ts,
    }


class TestCorrelate:
    def test_matches_within_window(self):
        alerts = [_make_alert(age_seconds=60)]
        anomalies = [_make_anomaly(age_seconds=30)]
        result = correlate(alerts, anomalies, time_window=300)
        assert len(result) == 1
        assert result[0].severity == "critical"
        assert "correlated:" in result[0].rule_id
        assert "data integrity" in result[0].message.lower()

    def test_skips_outside_window(self):
        alerts = [_make_alert(age_seconds=600)]  # 10 min ago
        anomalies = [_make_anomaly(age_seconds=30)]
        result = correlate(alerts, anomalies, time_window=300)
        assert len(result) == 0

    def test_skips_old_anomaly(self):
        alerts = [_make_alert(age_seconds=30)]
        anomalies = [_make_anomaly(age_seconds=600)]  # 10 min ago
        result = correlate(alerts, anomalies, time_window=300)
        assert len(result) == 0

    def test_no_false_correlations(self):
        # Normal alert + no anomalies = no correlation
        alerts = [_make_alert()]
        result = correlate(alerts, [], time_window=300)
        assert len(result) == 0

    def test_skips_acknowledged_alerts(self):
        alert = _make_alert()
        alert.acknowledged = True
        anomalies = [_make_anomaly()]
        result = correlate([alert], anomalies, time_window=300)
        assert len(result) == 0

    def test_multiple_alerts_multiple_anomalies(self):
        alerts = [
            _make_alert(rule_id="ram_critical", node_id="vm-1"),
            _make_alert(rule_id="cpu_high", node_id="vm-1"),
        ]
        anomalies = [
            _make_anomaly(metric="error_count_15m"),
            _make_anomaly(metric="lb_latency_ms", value=5000, z_score=3.5),
        ]
        result = correlate(alerts, anomalies, time_window=300)
        # 2 alerts x 2 anomalies = 4 correlations
        assert len(result) == 4
        assert all(r.severity == "critical" for r in result)

    def test_deduplicates_same_pair(self):
        # Same alert + same anomaly should only produce one correlation
        alert = _make_alert()
        anomaly = _make_anomaly()
        result = correlate([alert, alert], [anomaly], time_window=300)
        # alert appears twice but same (rule_id, node_id, metric) = deduped
        assert len(result) == 1


class TestEmptyInputs:
    def test_empty_alerts(self):
        result = correlate([], [_make_anomaly()], time_window=300)
        assert result == []

    def test_empty_anomalies(self):
        result = correlate([_make_alert()], [], time_window=300)
        assert result == []

    def test_both_empty(self):
        result = correlate([], [], time_window=300)
        assert result == []
