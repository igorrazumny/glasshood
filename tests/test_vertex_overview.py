# REQ-GHA-024: brief AI overviews of the system and each part. Vertex AI and Cloud Logging
# are faked; nothing here calls the network.

import json
import time

import pytest

from src.analysis import vertex_overview as ov


class _Resp:
    def __init__(self, code, body=None):
        self.status_code = code
        self._body = body or {}

    def json(self):
        return self._body


def _answer(obj, tin=1000, tout=100):
    return _Resp(200, {"candidates": [{"content": {"parts": [{"text": json.dumps(obj)}]}}],
                       "usageMetadata": {"promptTokenCount": tin, "candidatesTokenCount": tout}})


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(ov, "_system", {})
    monkeypatch.setattr(ov, "_parts", {})
    monkeypatch.setattr(ov, "_spend", {"day": "", "calls": 0, "input_tokens": 0, "output_tokens": 0,
                                       "cost_usd": 0.0, "capped": False})
    monkeypatch.setattr(ov, "_last_manual", 0.0)
    monkeypatch.setattr(ov, "_headers", lambda: {"Authorization": "Bearer t"})
    monkeypatch.setattr(ov, "_manifest_info", lambda: ({}, {}))


TOPO = {"overall_status": "healthy", "edges": [{"source": "cv-ip", "target": "vm-a"}], "nodes": [
    {"id": "cv-ip", "label": "cv-ip", "type": "load_balancer", "status": "healthy",
     "metrics": {"address": "1.2.3.4", "_check_description": "IN_USE"}},
    {"id": "vm-a", "label": "VM: a", "type": "vm", "status": "healthy", "metrics": {"_parent": "cv-mig"},
     "children": [{"id": "vm-a-docker", "label": "Docker Container", "status": "healthy",
                   "children": [{"id": "vm-a-api", "label": "ColdVault app", "status": "healthy"}]}]},
]}


def _route(monkeypatch, model_answer, seen=None):
    def post(url, json=None, headers=None, timeout=None):
        if "entries:list" in url:
            return _Resp(200, {"entries": [{"timestamp": "2026-11-06T00:00:00Z", "severity": "ERROR",
                                            "textPayload": "boom password=hunter2 Bearer abc.def"}]})
        if seen is not None:
            seen.append(json)
        return model_answer() if callable(model_answer) else model_answer
    monkeypatch.setattr(ov.httpx, "post", post)


def test_system_and_every_part_including_nested_get_an_overview(monkeypatch):
    _route(monkeypatch, _answer({"score": 9, "summary": "All fine.", "issues": [], "recommendations": []}))
    ov.run_all(TOPO)
    assert ov.get_system()["summary"] == "All fine."
    for pid in ("cv-ip", "vm-a", "vm-a-docker", "vm-a-api"):
        assert ov.get_part(pid)["summary"] == "All fine.", pid
    s = ov.get_system()
    assert s["model"] == ov.MODEL and s["analyzed_at"] and s["stale"] is False


def test_spend_is_recorded_and_the_daily_cap_stops_calls(monkeypatch):
    _route(monkeypatch, _answer({"summary": "ok"}, tin=2_000_000, tout=100_000))
    monkeypatch.setattr(ov, "DAILY_CALL_CAP", 2)
    ov.run_system(TOPO)
    ov.run_system(TOPO)
    sp = ov.get_spend()
    assert sp["calls"] == 2 and sp["input_tokens"] == 4_000_000
    assert sp["cost_usd"] == pytest.approx(4 * 0.25 + 0.2 * 1.50)
    ov.run_system(TOPO)  # third call is refused before reaching the model
    assert ov.get_spend()["capped"] is True
    assert "daily cap" in ov.get_system()["error"]
    assert ov.get_system()["summary"] == "ok"  # the last good overview is kept


def test_failure_keeps_last_good_and_says_why(monkeypatch):
    _route(monkeypatch, _answer({"summary": "first"}))
    ov.run_system(TOPO)
    _route(monkeypatch, _Resp(403))
    ov.run_system(TOPO)
    s = ov.get_system()
    assert s["summary"] == "first" and "HTTP 403" in s["error"]


def test_failure_with_nothing_yet_reports_no_overview(monkeypatch):
    _route(monkeypatch, _Resp(500))
    ov.run_system(TOPO)
    s = ov.get_system()
    assert s["summary"] == "" and s["analyzed_at"] is None and "HTTP 500" in s["error"]


def test_overview_older_than_its_schedule_is_stale(monkeypatch):
    _route(monkeypatch, _answer({"summary": "x"}))
    ov.run_system(TOPO)
    ov._system["analyzed_at"] = time.time() - ov.INTERVAL_S - 700
    assert ov.get_system()["stale"] is True


def test_no_secret_shaped_text_leaves_in_log_lines(monkeypatch):
    seen = []
    _route(monkeypatch, _answer({"summary": "x"}), seen)
    ov.run_system(TOPO)
    sent = seen[0]["contents"][0]["parts"][0]["text"]
    assert "hunter2" not in sent and "abc.def" not in sent and "[redacted]" in sent


def test_model_text_is_plain_data_bounded(monkeypatch):
    _route(monkeypatch, _answer({"score": 99, "summary": "s" * 2000, "issues": ["a"] * 9,
                                 "recommendations": [{"description": "r"}] * 9}))
    ov.run_system(TOPO)
    s = ov.get_system()
    assert s["score"] is None and len(s["summary"]) == 600
    assert len(s["issues"]) == 5 and s["recommendations"] == ["r", "r", "r"]


def test_manual_refresh_at_most_every_ten_minutes(monkeypatch):
    _route(monkeypatch, _answer({"summary": "x"}))
    assert ov.manual_refresh_allowed() == 0
    ov.manual_refresh(TOPO)
    assert 590 <= ov.manual_refresh_allowed() <= 600


def test_parts_use_the_label_the_reader_sees(monkeypatch):
    monkeypatch.setattr(ov, "_manifest_info", lambda: ({}, {"cv-ip": "Static IP"}))
    recs = {r["id"]: r for r, _ in ov._walk_parts(TOPO)}
    assert recs["cv-ip"]["label"] == "Static IP"
    assert recs["vm-a-api"]["inside"] == "Docker Container"
    assert "_check_description" not in recs["cv-ip"]["metrics"] and recs["cv-ip"]["check"] == "IN_USE"


def test_vm_parts_read_their_groups_log_filter(monkeypatch):
    monkeypatch.setattr(ov, "_manifest_info", lambda: ({"cv-mig": "resource.type=\"gce_instance\""}, {}))
    filters = {r["id"]: f for r, f in ov._walk_parts(TOPO)}
    assert filters["vm-a"] == 'resource.type="gce_instance"'
    assert filters["cv-ip"] == ""


def test_routes_viewer_reads_operator_refreshes(monkeypatch):
    from fastapi import HTTPException
    from src.api.routes import analysis as routes
    monkeypatch.setattr(routes, "verify_token", lambda r: None)
    monkeypatch.setattr(routes, "get_topology_data", lambda: TOPO)
    _route(monkeypatch, _answer({"summary": "x"}))

    class Req:
        def __init__(self, role):
            self.state = type("S", (), {"user_context": {"role": role}})()
    viewer = routes.get_analysis_endpoint(Req("viewer"))
    assert "spend" not in viewer
    with pytest.raises(HTTPException) as e:
        routes.refresh_analysis(Req("viewer"))
    assert e.value.status_code == 403
    assert routes.refresh_analysis(Req("operator"))["summary"] == "x"
    with pytest.raises(HTTPException) as e:
        routes.refresh_analysis(Req("operator"))
    assert e.value.status_code == 429
    assert "spend" in routes.get_analysis_endpoint(Req("operator"))
