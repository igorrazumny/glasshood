# File: tests/test_alert_detail.py
# Purpose: Tests for alert detail endpoints (list + acknowledge) and the
# topology-side anomaly classification wrapper (REQ-004).

from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI

from src.api.routes.alerts import router

_app = FastAPI()
_app.include_router(router)


def _mock_auth(request):
    request.state.user_role = "operator"
    request.state.user_context = {"user": "test@9r.ai", "role": "operator"}


@patch("src.api.routes.alerts.verify_token", side_effect=_mock_auth)
@patch("src.api.routes.alerts.require_role")
class TestAlertList:
    def _client(self):
        return TestClient(_app)

    def test_list_empty(self, mock_role, mock_auth):
        with patch("src.api.routes.alerts.get_alerts", return_value=[]):
            resp = self._client().get("/api/alerts")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0
        assert resp.json()["alerts"] == []

    def test_list_with_alerts(self, mock_role, mock_auth):
        alerts = [
            {"rule_id": "cpu_high", "severity": "critical", "message": "CPU > 90%",
             "triggered_at": "2026-03-18T06:00:00", "node_id": "vm-1"},
            {"rule_id": "latency", "severity": "warning", "message": "Latency > 1s",
             "triggered_at": "2026-03-18T06:01:00", "node_id": "lb-1"},
        ]
        with patch("src.api.routes.alerts.get_alerts", return_value=alerts):
            resp = self._client().get("/api/alerts")
        assert resp.status_code == 200
        assert resp.json()["count"] == 2

    def test_list_filter_severity(self, mock_role, mock_auth):
        alerts = [
            {"rule_id": "cpu_high", "severity": "critical", "message": "CPU > 90%",
             "triggered_at": "2026-03-18T06:00:00", "node_id": "vm-1"},
            {"rule_id": "latency", "severity": "warning", "message": "Latency > 1s",
             "triggered_at": "2026-03-18T06:01:00", "node_id": "lb-1"},
        ]
        with patch("src.api.routes.alerts.get_alerts", return_value=alerts):
            resp = self._client().get("/api/alerts?severity=critical")
        assert resp.status_code == 200
        assert resp.json()["count"] == 1
        assert resp.json()["alerts"][0]["rule_id"] == "cpu_high"


@patch("src.api.routes.alerts.verify_token", side_effect=_mock_auth)
@patch("src.api.routes.alerts.require_role")
class TestAlertAck:
    def _client(self):
        return TestClient(_app)

    def test_ack_success(self, mock_role, mock_auth):
        with patch("src.api.routes.alerts.acknowledge_alert", return_value=True):
            resp = self._client().post("/api/alerts/ack", json={
                "rule_id": "cpu_high",
                "node_id": "vm-1",
                "user": "operator@9r.ai",
            })
        assert resp.status_code == 200
        assert resp.json()["status"] == "acknowledged"
        assert resp.json()["rule_id"] == "cpu_high"

    def test_ack_not_found(self, mock_role, mock_auth):
        with patch("src.api.routes.alerts.acknowledge_alert", return_value=False):
            resp = self._client().post("/api/alerts/ack", json={
                "rule_id": "nonexistent",
                "user": "operator@9r.ai",
            })
        assert resp.status_code == 404

    def test_ack_without_node_id(self, mock_role, mock_auth):
        with patch("src.api.routes.alerts.acknowledge_alert", return_value=True) as mock_ack:
            resp = self._client().post("/api/alerts/ack", json={
                "rule_id": "global_error_spike",
                "user": "admin@9r.ai",
            })
        assert resp.status_code == 200
        mock_ack.assert_called_once_with("global_error_spike", None, "admin@9r.ai")

    def test_ack_requires_user(self, mock_role, mock_auth):
        resp = self._client().post("/api/alerts/ack", json={
            "rule_id": "cpu_high",
        })
        assert resp.status_code == 422  # missing required field


class TestApplyAnomalyClassification:
    """REQ-004: the topology-level classification wrapper cannot crash
    /api/topology even when classify_anomalies fails on a malformed anomaly."""

    def test_attaches_classification_when_anomalies_present(self):
        from src.api.routes.topology import _apply_anomaly_classification
        result = {}
        with patch("src.security.anomaly_detector.classify_anomalies",
                   return_value={"title": "Suspicious",
                                 "classification": "auth_anomaly",
                                 "business_impact": "x",
                                 "details": [], "actions": []}):
            _apply_anomaly_classification(result, [{"metric": "x", "value": 1}])
        assert result["anomaly_classification"]["title"] == "Suspicious"

    def test_empty_anomaly_list_does_not_call_classify(self):
        from src.api.routes.topology import _apply_anomaly_classification
        result = {}
        with patch("src.security.anomaly_detector.classify_anomalies") as mock_cls:
            _apply_anomaly_classification(result, [])
        mock_cls.assert_not_called()
        assert "anomaly_classification" not in result

    def test_exception_in_classify_does_not_raise(self):
        """The whole point of REQ-004 — a malformed anomaly must not 500 the route."""
        from src.api.routes.topology import _apply_anomaly_classification
        result = {"anomalies": [{"malformed": True}]}
        with patch("src.security.anomaly_detector.classify_anomalies",
                   side_effect=RuntimeError("boom")):
            # Should NOT raise
            _apply_anomaly_classification(result, [{"malformed": True}])
        # Field omitted on failure
        assert "anomaly_classification" not in result
        # Other fields untouched
        assert result["anomalies"] == [{"malformed": True}]
