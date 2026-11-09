# File: tests/test_glasshood_self.py
# Purpose: REQ-GHA-035 — GlassHood watching itself: its Azure resources, its logs and its own work

import time
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.collectors import azure_resources as az
from src.collectors import glasshood_self as gs

APP_ID = "/subscriptions/s/resourceGroups/rg/providers/Microsoft.App/containerApps/glasshood"


def test_container_app_running_its_newest_revision_is_healthy():
    b = az.box({"id": APP_ID}, get=lambda i: {"properties": {
        "provisioningState": "Succeeded", "runningStatus": "Running",
        "latestRevisionName": "glasshood--0000065", "latestReadyRevisionName": "glasshood--0000065"}})
    assert b["status"] == "healthy" and "glasshood--0000065" in b["check_description"]


def test_a_new_revision_that_is_not_ready_is_degraded():
    b = az.box({"id": APP_ID}, get=lambda i: {"properties": {
        "provisioningState": "Succeeded", "runningStatus": "Running",
        "latestRevisionName": "r66", "latestReadyRevisionName": "r65"}})
    assert b["status"] == "degraded" and "r66 is not ready" in b["check_description"]


def test_stopped_function_and_unavailable_storage_are_errors():
    assert az.box({"id": "x"}, get=lambda i: {"properties": {"state": "Stopped"}})["status"] == "error"
    assert az.box({"id": "x"}, get=lambda i: {"properties": {"provisioningState": "Succeeded",
                                                              "statusOfPrimary": "unavailable"}})["status"] == "error"


def test_an_unreadable_resource_is_never_healthy():
    def boom(i):
        raise PermissionError()
    b = az.box({"id": APP_ID}, get=boom)
    assert b["status"] == "not checked" and "could not read" in b["check_description"]


def test_the_api_version_follows_the_resource_type():
    assert az._api_version(APP_ID) == "2024-03-01"
    assert az._api_version("/subscriptions/s/resourceGroups/rg/providers/Microsoft.KeyVault/vaults/kv") == "2023-07-01"


def test_log_rows_become_log_lines_newest_first():
    data = {"tables": [{"columns": [{"name": "TimeGenerated"}, {"name": "Log_s"}],
                        "rows": [["2026-11-07T22:00:00Z", "ERROR something broke"], ["2026-11-07T21:59:00Z", "ok"]]}]}
    seen = {}

    def post(ws, kql):
        seen["kql"] = kql
        return data
    lines = az.query_logs("ws1", "ContainerAppConsoleLogs_CL | where ContainerAppName_s == 'glasshood'", 1, 5, post=post)
    assert [l["severity"] for l in lines] == ["ERROR", "INFO"]
    assert "ago(60m)" in seen["kql"] and "take 5" in seen["kql"] and "TimeGenerated <" not in seen["kql"]
    # REQ-GHA-032 clause 13: earlier lines are the ones before the oldest shown
    from datetime import datetime, timezone
    az.query_logs("ws1", "Q", 168, 5, post=post, before=datetime(2026, 11, 9, 10, 0, tzinfo=timezone.utc))
    assert "| where TimeGenerated <= datetime(2026-11-09T10:00:00.000000Z) | order by" in seen["kql"]


def test_a_stopped_loop_shows_as_stopped():
    assert gs._fresh(time.time() - 60, 600, "X")[0] == "healthy"
    assert gs._fresh(time.time() - 2000, 600, "X")[0] == "degraded"
    s, d = gs._fresh(time.time() - 4000, 600, "X")
    assert s == "error" and "stopped" in d


def test_a_task_that_never_runs_becomes_an_error_after_a_grace(monkeypatch):
    # shadow C1: measured from GlassHood's start
    monkeypatch.setattr(gs, "_STARTED", time.time() - 60)
    assert gs._fresh(None, 600, "X")[0] == "not checked"
    monkeypatch.setattr(gs, "_STARTED", time.time() - 48 * 3600)
    s, d = gs._fresh(None, 10800, "The AI log review")
    assert s == "error" and "has not run at all" in d


def test_a_never_started_review_raises_an_alarm_through_the_rules(monkeypatch):
    from src.models.topology import Node
    from src.rules import engine
    monkeypatch.setattr(gs, "_STARTED", time.time() - 48 * 3600)
    with patch("src.analysis.ai_review.status", return_value={"reviewed_at": None, "error": None, "interval_s": 10800}):
        r = gs.component("ai_review")
    engine._active.clear()
    rule = {"id": "node_error", "group": "status", "severity": "critical", "scope": "node",
            "condition": {"metric": "status", "operator": "==", "value": "error"}}
    monkeypatch.setattr(engine, "_rules", lambda path: [rule])
    engine.evaluate_rules([Node(id="gls-ai-review", label="AI log review", type="compute", status=r["status"])], {})
    assert [a["node_id"] for a in engine.get_alerts()] == ["gls-ai-review"]
    engine._active.clear()


def test_self_boxes_exist_even_before_the_first_landscape_round():
    from src.api.routes.topology import _refresh_self
    manifest = [{"nodes": [{"id": "gls-ai-review", "label": "AI log review", "type": "compute",
                            "monitoring": {"probe": {"type": "glasshood_self", "component": "ai_review"}}}]}]
    nodes = []
    with patch("src.api.routes.manifests._load_manifests", return_value=manifest), \
         patch("src.analysis.ai_review.status", return_value={"reviewed_at": time.time(), "error": None, "interval_s": 10800}):
        _refresh_self(nodes)
    assert [(n.id, n.status) for n in nodes] == [("gls-ai-review", "healthy")]


def test_a_failed_overview_refresh_shows_even_with_a_last_good_summary():
    # shadow C2: last good -> failed refresh -> recovered
    spend = {"capped": False}
    with patch("src.analysis.vertex_overview.get_spend", return_value=spend):
        with patch("src.analysis.vertex_overview.get_system",
                   return_value={"analyzed_at": time.time() - 60, "summary": "last good", "error": "Vertex AI HTTP 500"}):
            r = gs.component("ai_overview")
        assert r["status"] == "degraded" and "HTTP 500" in r["check_description"] and "last good" in r["check_description"]
        with patch("src.analysis.vertex_overview.get_system",
                   return_value={"analyzed_at": time.time() - 60, "summary": "new", "error": None}):
            assert gs.component("ai_overview")["status"] == "healthy"


def test_empty_or_transitioning_azure_answers_are_not_healthy():
    assert az.box({"id": "x"}, get=lambda i: {})["status"] == "not checked"
    b = az.box({"id": APP_ID}, get=lambda i: {"properties": {"provisioningState": "InProgress", "runningStatus": "Progressing",
                                                              "latestRevisionName": "r1", "latestReadyRevisionName": "r1"}})
    assert b["status"] == "degraded"


def test_coldvault_not_read_is_an_error_with_its_reason():
    with patch("src.collectors.coldvault.get_metrics_status",
               return_value={"read": False, "reason": "ColdVault refused the request (HTTP 401)", "checked_at": time.time()}):
        r = gs.component("coldvault_read")
    assert r["status"] == "error" and "HTTP 401" in r["check_description"]


def test_ai_overview_at_its_daily_cap_is_degraded():
    with patch("src.analysis.vertex_overview.get_system", return_value={"analyzed_at": time.time()}), \
         patch("src.analysis.vertex_overview.get_spend", return_value={"capped": True, "daily_call_cap": 1200, "calls": 1200}):
        r = gs.component("ai_overview")
    assert r["status"] == "degraded" and "cap" in r["check_description"]


def test_saving_before_the_first_save_is_not_an_error():
    with patch("src.analysis.ai_review.status", return_value={"saved": False, "saving_problem": None}):
        assert gs.component("saved_state")["status"] == "not checked"
    with patch("src.analysis.ai_review.status", return_value={"saved": False, "saving_problem": "disk full"}):
        assert gs.component("saved_state")["status"] == "error"


def test_glasshood_logs_come_from_its_log_workspace():
    from src.api.routes.logs import router
    app = FastAPI()
    app.include_router(router)
    rows = [{"timestamp": "t", "severity": "INFO", "message": "started"}]
    with patch("src.api.routes.logs.verify_token"), \
         patch("src.api.routes.logs._resolve_node", return_value=("azure_logs", "ws1", "ContainerAppConsoleLogs_CL")), \
         patch("src.collectors.azure_resources.query_logs", return_value=rows) as q:
        body = TestClient(app).get("/api/logs/gh-app").json()
    assert body["count"] == 1 and body["window"] == "1h"
    assert q.call_args.args[:2] == ("ws1", "ContainerAppConsoleLogs_CL")


def test_a_part_without_a_log_source_says_why():
    from src.api.routes.logs import _resolve_node, router
    manifest = [{"nodes": [{"id": "gh-site", "monitoring": {"logs": [{"source": "none", "reason": "A static website keeps no logs here."}]}}]}]
    with patch("src.api.routes.manifests._load_manifests", return_value=manifest), \
         patch("src.manifest_compiler.compile_all", return_value=manifest):
        assert _resolve_node("gh-site") == ("no_logs", None, "A static website keeps no logs here.")
    app = FastAPI()
    app.include_router(router)
    with patch("src.api.routes.logs.verify_token"), \
         patch("src.api.routes.logs._resolve_node", return_value=("no_logs", None, "A static website keeps no logs here.")):
        body = TestClient(app).get("/api/logs/gh-site").json()
    assert body["count"] == 0 and body["note"] == "A static website keeps no logs here."


def test_a_failed_overview_refresh_raises_a_warning_that_ends_on_recovery(monkeypatch):
    # shadow C2 remainder: through the rules, with the landscape's own warning rule
    import yaml
    from src.models.topology import Node
    from src.rules import engine
    rules = yaml.safe_load(SELF_ALARMS)
    monkeypatch.setattr(engine, "_rules", lambda path: rules)
    engine._active.clear()

    def run(system):
        with patch("src.analysis.vertex_overview.get_spend", return_value={"capped": False}), \
             patch("src.analysis.vertex_overview.get_system", return_value=system):
            r = gs.component("ai_overview")
        nodes = [Node(id="gls-ai-overview", label="AI overview", type="compute", status=r["status"]),
                 Node(id="cv-backend", label="Backend service", type="compute", status="degraded")]
        return [(a.node_id, a.severity) for a in engine.evaluate_rules(nodes, {})]
    assert run({"analyzed_at": time.time() - 60, "summary": "good", "error": None}) == []
    assert run({"analyzed_at": time.time() - 60, "summary": "good", "error": "Vertex AI HTTP 500"}) == [("gls-ai-overview", "warning")]
    assert run({"analyzed_at": time.time() - 30, "summary": "new", "error": None}) == []
    engine._active.clear()


SELF_ALARMS = """
- id: self_work_late
  name: GlassHood's own work
  group: status
  title: "{part}: GlassHood's own work is late or failing"
  description: GlassHood's own task is late or failing
  severity: warning
  scope: node
  parts: [gls-coldvault-read, gls-landscape-checks, gls-public-status, gls-ai-overview, gls-ai-review, gls-saved-state]
  condition: {metric: status, operator: ==, value: degraded}
"""
