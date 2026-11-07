# File: tests/test_statuspage.py
# Purpose: REQ-GHA-036 — public systems from what their provider publishes

from src.collectors import statuspage as sp
from src.rules import engine

URL = "https://status.example.com/api/v2/summary.json"
SUMMARY = {
    "page": {"name": "Example Status", "url": "https://status.example.com"},
    "components": [
        {"id": "c-ams", "name": "Amsterdam", "status": "operational", "updated_at": "2026-11-07T20:00:00Z"},
        {"id": "c-fra", "name": "Frankfurt", "status": "major_outage", "updated_at": "2026-11-07T21:00:00Z"},
    ],
    "incidents": [{"id": "inc1", "name": "Frankfurt unreachable", "status": "identified", "impact": "major",
                   "shortlink": "https://stspg.io/x",
                   "components": [{"id": "c-fra", "name": "Frankfurt"}],
                   "incident_updates": [{"created_at": "2026-11-07T21:05:00Z", "status": "identified",
                                         "body": "We found the cause."}]},
                  {"id": "old", "name": "Old", "status": "resolved", "impact": "minor",
                   "components": [{"id": "c-ams"}], "incident_updates": []}],
    "scheduled_maintenances": [],
}


def _fresh():
    sp._cache.clear()


def test_box_shows_the_provider_state_update_and_check_time():
    _fresh()
    b = sp.box({"url": URL, "component_id": "c-fra"}, fetch=lambda u: SUMMARY)
    assert b["status"] == "error"
    assert b["metrics"]["provider_status"] == "major outage"
    assert "provider update 2026-11-07 21:00 UTC" in b["check_description"] and "checked" in b["check_description"]


def test_a_failed_read_is_data_unavailable_never_healthy():
    _fresh()

    def boom(u):
        raise TimeoutError()
    b = sp.box({"url": URL, "component_id": "c-ams"}, fetch=boom)
    assert b["status"] == "not checked" and b["check_description"].startswith("Data unavailable")


def test_one_read_per_provider_serves_every_box():
    _fresh()
    calls = []
    sp.box({"url": URL, "component_id": "c-ams"}, fetch=lambda u: calls.append(u) or SUMMARY)
    sp.box({"url": URL, "component_id": "c-fra"}, fetch=lambda u: calls.append(u) or SUMMARY)
    assert len(calls) == 1


def test_open_incident_becomes_one_alarm_with_the_providers_words_and_link(monkeypatch):
    _fresh()
    monkeypatch.setattr(sp, "outside_systems", lambda: [("Example", URL, {"c-ams": "ex-ams", "c-fra": "ex-fra"})])
    entries, ok = sp.incidents(fetch=lambda u: SUMMARY)
    assert ok and len(entries) == 1
    [e] = entries
    assert e["part"] == "ex-fra" and e["severity"] == "critical"
    assert "We found the cause." in e["explanation"]["what"]
    assert any("https://stspg.io/x" in line for line in e["evidence"])


def test_the_alarm_ends_when_the_provider_resolves_it(monkeypatch):
    _fresh()
    engine._active.clear()
    monkeypatch.setattr(sp, "outside_systems", lambda: [("Example", URL, {"c-fra": "ex-fra"})])
    engine.track_provider_incidents(*sp.incidents(fetch=lambda u: SUMMARY))
    assert any(a["group"] == "provider:inc1" for a in engine.get_alerts())
    resolved = {**SUMMARY, "incidents": [{**SUMMARY["incidents"][0], "status": "resolved"}]}
    _fresh()
    engine.track_provider_incidents(*sp.incidents(fetch=lambda u: resolved))
    assert not any(a["group"] == "provider:inc1" for a in engine.get_alerts())
    engine._active.clear()


def test_an_unreadable_provider_changes_no_alarm(monkeypatch):
    _fresh()
    engine._active.clear()
    monkeypatch.setattr(sp, "outside_systems", lambda: [("Example", URL, {"c-fra": "ex-fra"})])
    engine.track_provider_incidents(*sp.incidents(fetch=lambda u: SUMMARY))
    _fresh()

    def boom(u):
        raise TimeoutError()
    entries, ok = sp.incidents(fetch=boom)
    assert not ok
    engine.track_provider_incidents(entries, ok)
    assert any(a["group"] == "provider:inc1" for a in engine.get_alerts())
    engine._active.clear()


def test_a_box_log_is_the_providers_published_updates(monkeypatch):
    _fresh()
    monkeypatch.setattr(sp, "outside_systems", lambda: [("Example", URL, {"c-ams": "ex-ams", "c-fra": "ex-fra"})])
    fra = sp.log_entries("ex-fra", fetch=lambda u: SUMMARY)
    assert fra["entries"] and "We found the cause." in fra["entries"][0]["message"]
    ams = sp.log_entries("ex-ams", fetch=lambda u: SUMMARY)
    assert ams["entries"] == [] and "publishes no open incident" in ams["note"]
    assert sp.log_entries("cv-mig", fetch=lambda u: SUMMARY) is None


def test_the_generated_landscape_holds_only_published_components():
    import importlib.util
    spec = importlib.util.spec_from_file_location("gen", "controller/landscapes/statuspage_landscape.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    land = gen.build(SUMMARY, URL, "example", "ex")
    env = land["environments"][0]
    assert land["kind"] == "outside_view"
    assert [n["label"] for n in env["nodes"]] == ["Amsterdam", "Frankfurt"]
    assert all(n["monitoring"]["probe"]["type"] == "statuspage" for n in env["nodes"])
    assert "built from what Example Status publishes" in env["display_name"]
