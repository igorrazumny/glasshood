# File: tests/test_outside_ai.py
# Purpose: REQ-GHA-036 clause 7 — external systems get AI overviews; a part's analysis is
# rewritten only when what the provider publishes about it changed

import json
from unittest.mock import patch

from src.analysis import vertex_overview as ov


def _published(status="operational", updated="2026-11-07T20:00:00Z", incident=None):
    comps = [{"id": "c1", "name": "Amsterdam", "status": status, "updated_at": updated, "group_id": "g"},
             {"id": "c2", "name": "Frankfurt", "status": "operational", "updated_at": updated, "group_id": "g"},
             {"id": "g", "name": "Europe", "group": True}]
    events = [incident] if incident else []
    return [{"name": "Example", "product": "example", "read": True, "error": None, "page": "https://status.example.com",
             "comps": {"c1": "ex-ams", "c2": "ex-fra"}, "components": comps, "events": events}]


def _reset():
    with ov._lock:
        ov._outside.clear(); ov._outside_sig.clear()
        for k in [k for k in ov._parts if k.startswith("ex-")]:
            del ov._parts[k]


def _run(published, calls):
    def gen(prompt, text):
        calls.append((prompt, json.loads(text)))
        return {"score": 8, "condition": "normal", "summary": "ok", "issues": [], "recommendations": []}
    with patch("src.collectors.statuspage.published", return_value=published), \
         patch.object(ov, "_generate", side_effect=gen):
        return ov.run_outside()


def test_each_external_system_gets_an_overview_and_each_part_an_analysis():
    _reset()
    calls = []
    written = _run(_published(), calls)
    assert written == 2
    assert ov.get_outside("example")["summary"] == "ok"
    assert ov.get_part("ex-ams")["summary"] == "ok"
    system_payload = [p for prompt, p in calls if prompt == ov.OUTSIDE_SYSTEM_PROMPT][0]
    assert system_payload["components_by_state"] == {"operational": 2}


def test_an_unchanged_part_is_not_rewritten():
    _reset()
    _run(_published(), [])
    calls = []
    assert _run(_published(), calls) == 0
    assert [p for p, _ in calls] == [ov.OUTSIDE_SYSTEM_PROMPT]   # only the system overview


def test_a_changed_part_is_rewritten_with_the_providers_words():
    _reset()
    _run(_published(), [])
    incident = {"id": "i1", "name": "Amsterdam degraded", "_kind": "incident", "status": "investigating",
                "impact": "minor", "components": [{"id": "c1", "name": "Amsterdam"}, {"id": "c2", "name": "Frankfurt"}],
                "incident_updates": [{"created_at": "2026-11-07T22:00:00Z", "status": "investigating",
                                      "body": "We are looking into packet loss."}]}
    calls = []
    written = _run(_published(status="degraded_performance", updated="2026-11-07T22:00:00Z", incident=incident), calls)
    assert written == 2   # Amsterdam changed state; Frankfurt is newly named by the incident
    part = [p for prompt, p in calls if prompt == ov.OUTSIDE_PART_PROMPT and p["component"] == "Amsterdam"][0]
    [inc] = part["open_incidents_and_maintenance"]
    assert inc["updates"][0]["text"] == "We are looking into packet loss."
    assert inc["also_affects"] == ["Frankfurt"]
    assert part["group"] == "Europe"


def test_an_unreadable_provider_keeps_the_last_overview_and_says_why():
    _reset()
    _run(_published(), [])
    down = [{"name": "Example", "product": "example", "read": False, "error": "the provider's status could not be read (TimeoutError)",
             "page": "", "comps": {}, "components": [], "events": []}]
    _run(down, [])
    o = ov.get_outside("example")
    assert o["summary"] == "ok" and "could not be read" in o["error"]


def test_prompts_forbid_invented_causes():
    for prompt in (ov.OUTSIDE_SYSTEM_PROMPT, ov.OUTSIDE_PART_PROMPT):
        assert "Never invent an internal cause" in prompt and "cannot be known from outside" in prompt


def test_edited_update_status_or_affected_parts_rewrite_the_analysis():
    # shadow C2: provider content can change without a new update timestamp
    _reset()
    inc = {"id": "i1", "name": "Amsterdam degraded", "_kind": "incident", "status": "investigating", "impact": "minor",
           "components": [{"id": "c1", "name": "Amsterdam"}],
           "incident_updates": [{"created_at": "2026-11-07T22:00:00Z", "status": "investigating", "body": "Looking into it."}]}
    _run(_published(incident=inc), [])
    assert _run(_published(incident=inc), []) == 0          # unchanged: no call
    edited = {**inc, "incident_updates": [{**inc["incident_updates"][0], "body": "Correction: only IPv6 traffic."}]}
    assert _run(_published(incident=edited), []) >= 1
    monitoring = {**edited, "status": "monitoring"}
    assert _run(_published(incident=monitoring), []) >= 1
    wider = {**monitoring, "components": [{"id": "c1", "name": "Amsterdam"}, {"id": "c2", "name": "Frankfurt"}]}
    assert _run(_published(incident=wider), []) == 2       # Amsterdam's record changed, Frankfurt newly named


def test_a_selected_external_system_never_shows_another_systems_overview():
    # shadow C1
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.api.routes.analysis import router
    _reset()
    app = FastAPI()
    app.include_router(router)
    manifests = [{"product": "coldvault", "kind": ""}, {"product": "cloudflare", "kind": "outside_view"}]
    with patch("src.api.routes.analysis.verify_token"), \
         patch("src.api.routes.manifests._load_manifests", return_value=manifests), \
         patch.object(ov, "get_system", return_value={"summary": "ColdVault is healthy", "score": 9}):
        c = TestClient(app)
        body = c.get("/api/analysis?system=cloudflare").json()
        assert body["summary"] == "" and "not been written yet" in body["error"]
        assert c.get("/api/analysis?system=nope").status_code == 404
        # an own system without its own overview yet says so; never the combined one in its place
        assert "not been written yet" in c.get("/api/analysis?system=coldvault").json()["error"]
        assert c.get("/api/analysis").json()["summary"] == "ColdVault is healthy"


def test_each_own_system_gets_its_own_overview_and_card_description():
    # REQ-GHA-037
    with ov._lock:
        ov._own.clear()
    calls = []

    def gen(prompt, text):
        payload = json.loads(text)
        calls.append(payload)
        return {"score": 9, "condition": "normal", "summary": f"{payload['system']} is running normally.", "issues": [], "recommendations": []}
    topology = {"nodes": [{"id": "cv-a", "label": "App", "project": "coldvault", "status": "healthy", "metrics": {}},
                          {"id": "gls-a", "label": "Backend", "project": "glasshood", "status": "healthy", "metrics": {}},
                          {"id": "cf-a", "label": "AMS", "project": "cloudflare", "status": "healthy", "metrics": {}}]}
    manifests = [{"product": "coldvault", "project_id": ov.PROJECT}, {"product": "glasshood", "project_id": ""},
                 {"product": "cloudflare", "kind": "outside_view"}]
    with patch("src.api.routes.manifests._load_manifests", return_value=manifests), \
         patch.object(ov, "_generate", side_effect=gen), \
         patch.object(ov, "_log_lines", return_value=["a log line"]) as logs:
        ov.run_own_systems(topology)
    assert sorted(c["system"] for c in calls) == ["coldvault", "glasshood"]     # no external system here
    assert [c["recent_logs"] for c in calls if c["system"] == "coldvault"] == [["a log line"]]
    assert [c["recent_logs"] for c in calls if c["system"] == "glasshood"] == [[]]
    assert [p["label"] for c in calls if c["system"] == "glasshood" for p in c["parts"]] == ["Backend"]
    cards = ov.system_cards()
    assert cards["coldvault"]["summary"] == "coldvault is running normally."
    assert ov.get_own("glasshood")["summary"] == "glasshood is running normally."


def test_a_manual_refresh_renews_each_systems_own_overview():
    # shadow P1: refresh while viewing ColdVault must update ColdVault's own assessment
    with patch.object(ov, "refresh_durable_spend"), patch.object(ov, "run_system") as sys_, \
         patch.object(ov, "run_own_systems") as own, patch.object(ov, "run_outside") as out:
        ov.manual_refresh({"nodes": []})
    sys_.assert_called_once(); own.assert_called_once()
    out.assert_called_once_with(parts=False, topology={"nodes": []})


def test_outside_overview_without_parts_writes_no_part_analysis():
    _reset()
    calls = []
    def gen(prompt, text):
        calls.append(prompt)
        return {"score": 8, "condition": "normal", "summary": "ok", "issues": [], "recommendations": []}
    with patch("src.collectors.statuspage.published", return_value=_published()), \
         patch.object(ov, "_generate", side_effect=gen):
        assert ov.run_outside(parts=False) == 0
    assert calls == [ov.OUTSIDE_SYSTEM_PROMPT]
