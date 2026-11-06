# File: src/security/anomaly_detector.py
# Purpose: Statistical anomaly detection on collector data — z-score against rolling baselines

import collections
import logging
import math
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_anomalies: list[dict] = []
_lock = threading.Lock()

# ALCOA+ audit trail for anomaly detection cycles
_audit_log: collections.deque = collections.deque(maxlen=200)

# Which collector reading each metric was last judged on, and the verdict
# (REQ-GHA-026): a page view repeats the verdict, only a fresh reading changes it.
_judged: dict[str, tuple[float, dict | None]] = {}

# Which collector stats dict carries each metric; its "read_at" marks a fresh reading
_METRIC_SOURCE = {
    "error_count_15m": "logging",
    "lb_latency_ms": "monitoring",
    "lb_request_count_1h": "monitoring",
    "vm_cpu_percent": "monitoring",
}


class BaselineTracker:
    """Rolling window statistics per metric. Tracks mean and stddev.

    A point is kept while it is at most window_seconds older than the newest
    point of that metric, and at most window_size points are kept."""

    def __init__(self, window_size: int = 60, min_points: int = 5,
                 window_seconds: float | None = None):
        self.window_size = window_size
        self.min_points = min_points
        self.window_seconds = window_seconds
        self._data: dict[str, collections.deque] = {}

    def update(self, metric: str, value: float, ts: float | None = None) -> None:
        """Add a data point (taken at ts, default now) to the rolling window."""
        ts = time.time() if ts is None else ts
        window = self._data.setdefault(metric, collections.deque(maxlen=self.window_size))
        window.append((ts, value))
        if self.window_seconds:
            while window and window[0][0] < ts - self.window_seconds:
                window.popleft()

    def get_stats(self, metric: str) -> dict:
        """Return mean, stddev, count for a metric."""
        values = [v for _, v in self._data.get(metric, [])]
        n = len(values)
        if n == 0:
            return {"mean": 0.0, "stddev": 0.0, "count": 0}
        mean = sum(values) / n
        if n < 2:
            return {"mean": mean, "stddev": 0.0, "count": n}
        variance = sum((v - mean) ** 2 for v in values) / (n - 1)
        return {"mean": mean, "stddev": math.sqrt(variance), "count": n}

    def is_anomalous(self, metric: str, value: float, sigma: float = 3.0,
                     min_change: float = 0.0) -> tuple[bool, float]:
        """Check if value is anomalous. Returns (is_anomaly, z_score).
        Returns (False, 0.0) if insufficient data points.

        A change smaller than min_change never counts, and the spread used for
        the z-score is never below min_change, so a flat baseline cannot make a
        small step look infinitely unusual (REQ-GHA-026)."""
        stats = self.get_stats(metric)
        if stats["count"] < self.min_points:
            return False, 0.0
        delta = value - stats["mean"]
        if abs(delta) < min_change or delta == 0:
            return False, 0.0
        spread = max(stats["stddev"], min_change)
        if spread == 0:
            # Flat baseline and no minimum change configured: a warning at most
            return True, 0.0
        z_score = delta / spread
        return abs(z_score) > sigma, z_score

    def all_baselines(self) -> dict:
        """Return all current baselines for debugging."""
        return {metric: self.get_stats(metric) for metric in self._data}


_tracker = BaselineTracker()


def _load_config(path: str) -> dict:
    """Load anomaly detection config from YAML."""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        with open(p) as f:
            data = yaml.safe_load(f) or {}
        return data.get("anomaly_detection", {})
    except Exception as e:
        logger.error(f"Failed to load anomaly config: {e}")
        return {}


def _current_values(monitoring_stats: dict, logging_stats: dict) -> dict:
    sources = {"monitoring": monitoring_stats, "logging": logging_stats}
    return {metric: sources[src].get(metric) for metric, src in _METRIC_SOURCE.items()}


def update_baselines(monitoring_stats: dict, logging_stats: dict) -> None:
    """Feed current collector data into baseline tracker."""
    for metric, value in _current_values(monitoring_stats, logging_stats).items():
        if value is not None:
            _tracker.update(metric, float(value))


def _judge(metric: str, value: float, config: dict, now_iso: str) -> dict | None:
    """Judge one reading against the baseline as it stands. Returns an anomaly or None."""
    mc = config.get("metrics", {}).get(metric, {})
    sigma = mc.get("sigma", config.get("sigma_threshold", 3.0))
    min_change = float(mc.get("min_change", 0.0))
    fallback = mc.get("fallback_threshold")

    is_anomaly, z_score = _tracker.is_anomalous(metric, value, sigma, min_change)

    # Fallback: if baseline not warmed up, use static threshold
    if not is_anomaly and fallback is not None:
        stats = _tracker.get_stats(metric)
        if stats["count"] < config.get("min_data_points", 5):
            is_anomaly = value > float(fallback)
            z_score = 0.0  # no z-score for fallback

    if not is_anomaly:
        return None
    baseline = _tracker.get_stats(metric)
    confidence = min(abs(z_score) / 5.0, 1.0) if z_score != 0 else 0.5
    return {
        "type": "statistical_anomaly",
        "metric": metric,
        "value": value,
        "baseline_mean": round(baseline["mean"], 2),
        "baseline_stddev": round(baseline["stddev"], 2),
        "z_score": round(z_score, 2),
        "confidence": round(confidence, 2),
        "severity": "critical" if confidence > 0.8 else "warning",
        "timestamp": now_iso,
    }


def detect_anomalies(monitoring_stats: dict, logging_stats: dict,
                     security_stats: dict) -> list[dict]:
    """Detect statistical anomalies in current metrics. Returns anomaly list.

    A metric whose source carries "read_at" (the time of its last successful
    collector reading) is judged once per reading, against the baseline before
    that reading, and the reading is then added to the baseline; later calls
    for the same reading repeat that verdict (REQ-GHA-026). A source without
    "read_at" is judged against the baseline without changing it."""
    from src.config.settings import ANOMALY_CONFIG_PATH
    config = _load_config(ANOMALY_CONFIG_PATH)
    if not config.get("enabled", True):
        return []
    _tracker.window_seconds = config.get("window_seconds", 3600)
    _tracker.min_points = config.get("min_data_points", _tracker.min_points)

    now_iso = datetime.now(timezone.utc).isoformat()
    read_at = {"monitoring": monitoring_stats.get("read_at"),
               "logging": logging_stats.get("read_at")}

    detected = []
    judged_now = 0
    for metric, value in _current_values(monitoring_stats, logging_stats).items():
        if value is None:
            continue
        reading = read_at[_METRIC_SOURCE[metric]]
        if reading is None:
            anomaly = _judge(metric, float(value), config, now_iso)
        elif metric in _judged and _judged[metric][0] == reading:
            anomaly = _judged[metric][1]
        else:
            anomaly = _judge(metric, float(value), config, now_iso)
            _tracker.update(metric, float(value), ts=float(reading))
            _judged[metric] = (reading, anomaly)
            judged_now += 1
        if anomaly:
            detected.append(anomaly)

    with _lock:
        _anomalies[:] = detected

    if judged_now or not any(read_at.values()):
        # ALCOA+ audit trail: one entry per evaluation of fresh data
        _audit_log.append({
            "timestamp": now_iso,
            "action": "detect",
            "metrics_checked": len([v for v in _current_values(monitoring_stats, logging_stats).values()
                                    if v is not None]),
            "anomalies_found": len(detected),
        })
        if detected:
            logger.info(f"Anomaly detection: {len(detected)} anomalies "
                        f"({sum(1 for a in detected if a['severity'] == 'critical')} critical)")

    return detected


# Human-readable metric descriptions for alert presentation
METRIC_INFO = {
    "lb_latency_ms": {
        "name": "Load Balancer Response Time",
        "unit": "ms",
        "high_means": "The system is responding much slower than normal",
        "business_impact": "Users may experience slow page loads and API timeouts",
    },
    "error_count_15m": {
        "name": "Application Errors (15 min)",
        "unit": "errors",
        "high_means": "The application is producing more errors than usual",
        "business_impact": "Some user requests may be failing or returning incorrect results",
    },
    "lb_request_count_1h": {
        "name": "Request Volume (1 hour)",
        "unit": "requests",
        "high_means": "Traffic to the system has increased significantly",
        "business_impact": "Unusually high traffic — could indicate legitimate demand or an attack",
    },
    "vm_cpu_percent": {
        "name": "VM CPU Usage",
        "unit": "%",
        "high_means": "Server processors are under heavy load",
        "business_impact": "System may become slow or unresponsive if load continues",
    },
}


def classify_anomalies(anomalies: list[dict]) -> dict:
    """Classify anomaly pattern into a human-readable category with actions.

    Returns {classification, title, business_impact, actions, details}.
    """
    if not anomalies:
        return None

    anomalous = {a["metric"] for a in anomalies}
    high_latency = "lb_latency_ms" in anomalous
    high_errors = "error_count_15m" in anomalous
    high_traffic = "lb_request_count_1h" in anomalous
    high_cpu = "vm_cpu_percent" in anomalous

    # Classification rules (deterministic, hedged language)
    if high_errors and high_traffic:
        classification = "Possible Security Incident"
        title = "Unusual Error Surge With High Traffic"
        impact = "Service may be under attack or experiencing a major failure. User requests are failing."
        actions = [
            "Security: Review Cloud Armor logs for blocked requests and attack patterns",
            "IT: Open a priority incident and notify the security team",
            "Engineer: Check application error logs for root cause",
            "Business: Escalate to platform and security teams immediately",
        ]
    elif high_errors:
        classification = "Application Error Surge"
        title = "Application Producing Abnormal Number of Errors"
        impact = "Some user requests are failing. Data integrity may be affected."
        actions = [
            "Engineer: Check application logs for error patterns and stack traces",
            "IT: Monitor error rate — open incident if sustained over 10 minutes",
            "Business: Inform stakeholders that service quality is degraded",
        ]
    elif high_latency and high_cpu:
        classification = "Likely Resource Exhaustion"
        title = "System Overloaded — Slow Response and High CPU"
        impact = "Users are experiencing slow responses. The servers are struggling to keep up."
        actions = [
            "Engineer: Check if MIG autoscaler is adding VMs. Review CPU-intensive processes",
            "IT: Consider manual scaling if autoscaler is insufficient",
            "Business: Users may experience delays — platform team is investigating",
        ]
    elif high_latency and high_traffic:
        classification = "Likely Traffic Spike"
        title = "Unusually High Traffic Causing Slow Responses"
        impact = "Legitimate traffic surge or potential DDoS. Users experiencing slower responses."
        actions = [
            "Engineer: Verify traffic is legitimate. Check Cloud Armor for attack patterns",
            "IT: Monitor if autoscaler is responding. Consider traffic throttling",
            "Business: Service is slower due to high demand — team is monitoring",
        ]
    elif high_cpu:
        classification = "Likely Resource Exhaustion"
        title = "Server CPU Usage Abnormally High"
        impact = "Servers are under heavy load. Performance may degrade if sustained."
        actions = [
            "Engineer: Identify CPU-intensive processes. Check for stuck requests or memory leaks",
            "IT: Monitor MIG autoscaler response. Scale manually if needed",
        ]
    elif high_latency:
        classification = "Performance Degradation"
        title = "System Responding Slower Than Normal"
        impact = "Users may notice slower page loads and API responses."
        actions = [
            "Engineer: Check backend VM health and load balancer error rates",
            "IT: Monitor — escalate if sustained over 15 minutes",
        ]
    elif high_traffic:
        classification = "Traffic Anomaly"
        title = "Unusual Traffic Volume Detected"
        impact = "Request volume is significantly different from normal patterns."
        actions = [
            "Security: Verify traffic is legitimate — check for bot patterns",
            "Engineer: Monitor system capacity and autoscaler behavior",
        ]
    else:
        classification = "Infrastructure Anomaly"
        title = "Unexpected Infrastructure Metric Deviation"
        impact = "A monitored metric has deviated significantly from its normal baseline."
        actions = [
            "Engineer: Review the specific metric details below and investigate",
            "IT: Monitor for persistence — escalate if condition doesn't resolve within 30 minutes",
        ]

    # Build detail lines per anomaly
    details = []
    for a in anomalies:
        info = METRIC_INFO.get(a["metric"], {})
        name = info.get("name", a["metric"])
        val = a["value"]
        baseline = a["baseline_mean"]
        if baseline > 0 and val == 0:
            comparison = "dropped to 0"
        elif baseline > 0:
            ratio = val / baseline
            if ratio >= 2:
                comparison = f"{ratio:.0f}x higher than normal"
            elif ratio >= 1.5:
                comparison = f"{ratio:.1f}x higher than normal"
            elif ratio <= 0.5:
                comparison = f"{1/ratio:.0f}x lower than normal"
            else:
                comparison = f"{'above' if val > baseline else 'below'} normal"
        else:
            comparison = f"current value: {val:.1f}"
        details.append({
            "metric": a["metric"],
            "name": name,
            "summary": f"{name}: {val:.0f}{info.get('unit', '')} — {comparison}",
            "what_it_means": info.get("high_means", ""),
            "value": val,
            "baseline": baseline,
            "z_score": a.get("z_score", 0),
            "confidence": a.get("confidence", 0),
        })

    return {
        "classification": classification,
        "title": title,
        "business_impact": impact,
        "actions": actions,
        "details": details,
    }


def get_anomalies() -> list[dict]:
    """Return current detected anomalies."""
    with _lock:
        return list(_anomalies)


def get_stats() -> dict:
    """Return summary stats for rule engine integration."""
    with _lock:
        return {
            "anomaly_count": len(_anomalies),
            "high_confidence_count": sum(1 for a in _anomalies if a.get("confidence", 0) > 0.8),
        }


def get_baseline_stats() -> dict:
    """Return current baseline stats for debugging."""
    return _tracker.all_baselines()


def get_audit_log() -> list[dict]:
    """Return ALCOA+ audit trail entries (most recent first)."""
    return list(reversed(_audit_log))
