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
    assert "ago(60m)" in seen["kql"] and "take 5" in seen["kql"]


def test_a_stopped_loop_shows_as_stopped():
    assert gs._fresh(time.time() - 60, 600, "X")[0] == "healthy"
    assert gs._fresh(time.time() - 2000, 600, "X")[0] == "degraded"
    s, d = gs._fresh(time.time() - 4000, 600, "X")
    assert s == "error" and "stopped" in d
    assert gs._fresh(None, 600, "X")[0] == "not checked"


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
