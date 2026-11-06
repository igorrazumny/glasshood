# REQ-GHA-024: brief AI overviews of the system and each part. Vertex AI, Cloud Logging and
# Cloud Monitoring are faked; nothing here calls the network.

import json
import re
import threading
import time
from pathlib import Path

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


MON = {"calls": 0, "in": 0, "out": 0}


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(ov, "_system", {})
    monkeypatch.setattr(ov, "_parts", {})
    monkeypatch.setattr(ov, "_spend", {})
    monkeypatch.setattr(ov, "_last_manual", 0.0)
    monkeypatch.setattr(ov, "_headers", lambda: {"Authorization": "Bearer t"})
    monkeypatch.setattr(ov, "_manifest_info", lambda: ({}, {}))
    MON.update(calls=0, **{"in": 0, "out": 0})
    monkeypatch.setattr(ov, "_monitoring_today", lambda: dict(MON))
    ov.refresh_durable_spend()


TOPO = {"overall_status": "healthy", "edges": [{"source": "cv-ip", "target": "vm-a"}], "nodes": [
    {"id": "cv-ip", "label": "cv-ip", "type": "load_balancer", "status": "healthy",
     "metrics": {"address": "1.2.3.4", "_check_description": "IN_USE"}},
    {"id": "vm-a", "label": "VM: a", "type": "vm", "status": "healthy", "metrics": {"_parent": "cv-mig"},
     "children": [{"id": "vm-a-docker", "label": "Docker Container", "status": "healthy",
                   "children": [{"id": "vm-a-api", "label": "ColdVault app", "status": "healthy"}]}]},
]}


def _route(monkeypatch, model_answer, seen=None, entries=None):
    def post(url, json=None, headers=None, timeout=None):
        if "entries:list" in url:
            return _Resp(200, {"entries": entries if entries is not None else [
                {"timestamp": "2026-11-06T00:00:00Z", "severity": "ERROR",
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


def test_the_daily_cap_survives_a_restart(monkeypatch):
    """B3: a fresh process on the same day starts from Google's own count, not from zero."""
    _route(monkeypatch, _answer({"summary": "ok"}))
    monkeypatch.setattr(ov, "DAILY_CALL_CAP", 2)
    ov.run_system(TOPO)
    ov.run_system(TOPO)
    MON.update(calls=2, **{"in": 2000, "out": 200})      # what Monitoring now reports
    monkeypatch.setattr(ov, "_spend", {})                 # the process restarts
    ov.refresh_durable_spend()
    ov.run_system(TOPO)
    assert ov.get_spend()["calls"] == 2 and "daily cap" in ov.get_system()["error"]


def test_a_monitoring_delay_never_lowers_the_count(monkeypatch):
    _route(monkeypatch, _answer({"summary": "ok"}))
    ov.run_system(TOPO)
    ov.run_system(TOPO)
    ov.refresh_durable_spend()                            # Monitoring still says 0
    assert ov.get_spend()["calls"] == 2


def test_unreadable_usage_fails_closed(monkeypatch):
    _route(monkeypatch, _answer({"summary": "ok"}))

    def boom():
        raise RuntimeError("Cloud Monitoring HTTP 403")
    monkeypatch.setattr(ov, "_spend", {})
    monkeypatch.setattr(ov, "_monitoring_today", boom)
    ov.refresh_durable_spend()
    ov.run_system(TOPO)
    assert "could not be read" in ov.get_system()["error"]
    assert ov.get_spend()["calls"] == 0 and ov.get_spend()["usage_read"] is False


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


def test_input_failures_are_reported_too(monkeypatch):
    """B4: a credential refresh failing while reading logs is an error with a reason."""
    monkeypatch.setattr(ov, "_manifest_info", lambda: ({"cv-mig": 'resource.type="gce_instance"'}, {}))
    _route(monkeypatch, _answer({"summary": "first"}))
    ov.run_all(TOPO)

    class RefreshError(Exception):
        pass

    def boom(*a, **k):
        raise RefreshError("token expired")
    monkeypatch.setattr(ov, "_log_lines", boom)
    ov.run_all(TOPO)
    assert "RefreshError" in ov.get_system()["error"] and ov.get_system()["summary"] == "first"
    assert ov.get_part("vm-a")["summary"] == "first" and "RefreshError" in ov.get_part("vm-a")["error"]


def test_an_answer_without_a_summary_does_not_replace_the_last_good(monkeypatch):
    """W2"""
    _route(monkeypatch, _answer({"summary": "LAST GOOD"}))
    ov.run_system(TOPO)
    _route(monkeypatch, _answer({"score": 9}))
    ov.run_system(TOPO)
    s = ov.get_system()
    assert s["summary"] == "LAST GOOD" and "no summary" in s["error"]


def test_overview_older_than_its_schedule_is_stale(monkeypatch):
    """W3: no grace period."""
    _route(monkeypatch, _answer({"summary": "x"}))
    ov.run_system(TOPO)
    ov._system["analyzed_at"] = time.time() - ov.INTERVAL_S - 1
    assert ov.get_system()["stale"] is True


CANARY_TOPO = {"overall_status": "healthy", "edges": [], "nodes": [
    {"id": "n", "label": "n", "type": "x", "status": "healthy",
     "metrics": {"_check_description": "token=CANARY_CHECK", "api_key": "CANARY_METRIC",
                 "nested": {"Authorization": "Bearer CANARY_NESTED"}}}]}


def test_no_credential_value_leaves_in_any_field(monkeypatch):
    """B2: JSON logs, checks, metrics, nested fields — all sanitised; no alert text is sent."""
    seen = []
    entries = [{"timestamp": "t", "severity": "ERROR", "jsonPayload": {"password": "CANARY_JSON_LOG", "x": 1}},
               {"timestamp": "t", "severity": "ERROR", "jsonPayload": {"message": '{"secret": "CANARY_MSG"}'}},
               {"timestamp": "t", "severity": "ERROR", "textPayload": "login password=hunter2 Bearer abc.def"}]
    _route(monkeypatch, _answer({"summary": "x"}), seen, entries)
    ov.run_system({**CANARY_TOPO, "alerts": [{"message": "CANARY_ALERT"}]})
    ov.run_all(CANARY_TOPO)
    sent = " ".join(b["contents"][0]["parts"][0]["text"] for b in seen)
    for canary in ("CANARY_JSON_LOG", "CANARY_MSG", "CANARY_CHECK", "CANARY_METRIC", "CANARY_NESTED",
                   "CANARY_ALERT", "hunter2", "abc.def"):
        assert canary not in sent, canary
    assert "[redacted" in sent


def test_sanitize_keeps_structure():
    assert ov.sanitize({"a": [{"token": "x"}, "password: y"], "n": 3}) == \
        {"a": [{"token": "[redacted]"}, "[redacted line]"], "n": 3}


def test_free_text_credentials_go_whole(monkeypatch):
    """B2: the whole credential value or block leaves, not only its marker."""
    seen = []
    pem = "-----BEGIN PRIVATE KEY-----\nCANARY_PEM_BODY\n-----END PRIVATE KEY-----"
    entries = [
        {"timestamp": "t", "severity": "ERROR", "textPayload": "Authorization: Basic Q0FOQVJZX0JBU0lDOnB3"},
        {"timestamp": "t", "severity": "ERROR", "textPayload": f"loaded key {pem} ok"},
        {"timestamp": "t", "severity": "ERROR", "textPayload": 'config password = "CANARY quoted with spaces"'},
        {"timestamp": "t", "severity": "ERROR", "textPayload": "first line fine\nsecret: CANARY_MULTILINE tail"},
        {"timestamp": "t", "severity": "ERROR", "jsonPayload": {"message": "ctx\\nAuthorization: Basic CANARY_ESCAPED"}},
    ]
    _route(monkeypatch, _answer({"summary": "x"}), seen, entries)
    ov.run_system(TOPO)
    sent = seen[0]["contents"][0]["parts"][0]["text"]
    for canary in ("Q0FOQVJZX0JBU0lDOnB3", "CANARY_PEM_BODY", "END PRIVATE KEY", "CANARY quoted",
                   "CANARY_MULTILINE", "CANARY_ESCAPED"):
        assert canary not in sent, canary
    assert "first line fine" in sent  # only the credential line goes


def test_a_failed_read_after_a_good_one_stops_calls(monkeypatch):
    """B3: availability is invalidated on every failed read."""
    _route(monkeypatch, _answer({"summary": "ok"}))
    ov.run_system(TOPO)
    calls = ov.get_spend()["calls"]

    def boom():
        raise RuntimeError("Cloud Monitoring HTTP 503")
    monkeypatch.setattr(ov, "_monitoring_today", boom)
    ov.refresh_durable_spend()
    ov.run_system(TOPO)
    assert ov.get_spend()["calls"] == calls and ov.get_spend()["usage_read"] is False
    assert "could not be read" in ov.get_system()["error"]


def test_model_text_is_plain_data_bounded(monkeypatch):
    _route(monkeypatch, _answer({"score": 99, "summary": "s" * 2000, "issues": ["a"] * 9,
                                 "recommendations": [{"description": "r"}] * 9}))
    ov.run_system(TOPO)
    s = ov.get_system()
    assert s["score"] is None and len(s["summary"]) == 600
    assert len(s["issues"]) == 5 and s["recommendations"] == ["r", "r", "r"]


def test_manual_refresh_slot_is_taken_atomically(monkeypatch):
    """W1: two simultaneous requests — exactly one gets the slot."""
    results = []
    barrier = threading.Barrier(8)

    def go():
        barrier.wait()
        results.append(ov.reserve_manual_refresh())
    threads = [threading.Thread(target=go) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(0) == 1 and all(590 <= r <= 600 for r in results if r)


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


def test_every_overview_helper_a_component_uses_is_imported():
    """B1 guard: a helper from utils/overview.js called in a component must be imported there."""
    helpers = re.findall(r"export function (\w+)", Path("frontend/src/utils/overview.js").read_text())
    for jsx in Path("frontend/src/components").glob("*.jsx"):
        src = jsx.read_text()
        imported = set()
        for names in re.findall(r"import \{([^}]*)\} from '\.\./utils/overview(?:\.js)?'", src):
            imported |= {n.strip() for n in names.split(",")}
        for h in helpers:
            if re.search(rf"\b{h}\(", src):
                assert h in imported, f"{jsx.name} calls {h} without importing it"
