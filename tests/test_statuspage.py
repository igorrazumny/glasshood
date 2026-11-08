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
    entries, read = sp.incidents(fetch=lambda u: SUMMARY)
    assert read == {"Example"} and len(entries) == 1
    [e] = entries
    assert e["part"] == "ex-fra" and e["severity"] == "critical"
    assert "We found the cause." in e["explanation"]["what"]
    assert any("https://stspg.io/x" in line for line in e["evidence"])


def test_the_alarm_ends_when_the_provider_resolves_it(monkeypatch):
    _fresh()
    engine._active.clear()
    monkeypatch.setattr(sp, "outside_systems", lambda: [("Example", URL, {"c-fra": "ex-fra"})])
    engine.track_provider_incidents(*sp.incidents(fetch=lambda u: SUMMARY))
    assert any(a["group"] == "provider:Example:inc1" for a in engine.get_alerts())
    resolved = {**SUMMARY, "incidents": [{**SUMMARY["incidents"][0], "status": "resolved"}]}
    _fresh()
    engine.track_provider_incidents(*sp.incidents(fetch=lambda u: resolved))
    assert not any(a["group"] == "provider:Example:inc1" for a in engine.get_alerts())
    engine._active.clear()


def test_an_unreadable_provider_changes_no_alarm(monkeypatch):
    _fresh()
    engine._active.clear()
    monkeypatch.setattr(sp, "outside_systems", lambda: [("Example", URL, {"c-fra": "ex-fra"})])
    engine.track_provider_incidents(*sp.incidents(fetch=lambda u: SUMMARY))
    _fresh()

    def boom(u):
        raise TimeoutError()
    entries, read = sp.incidents(fetch=boom)
    assert read == set()
    engine.track_provider_incidents(entries, read)
    assert any(a["group"] == "provider:Example:inc1" for a in engine.get_alerts())
    engine._active.clear()


URL_B = "https://status.other.com/api/v2/summary.json"


def test_one_unreadable_provider_does_not_hold_back_anothers_recovery(monkeypatch):
    # shadow C1: A resolves its incident while B cannot be read; A's alarm ends, B's stays
    _fresh()
    engine._active.clear()
    b_summary = {**SUMMARY, "incidents": [{**SUMMARY["incidents"][0], "id": "incB"}]}
    monkeypatch.setattr(sp, "outside_systems", lambda: [("A", URL, {"c-fra": "a-fra"}), ("B", URL_B, {"c-fra": "b-fra"})])
    engine.track_provider_incidents(*sp.incidents(fetch=lambda u: SUMMARY if u == URL else b_summary))
    assert {a["group"] for a in engine.get_alerts()} == {"provider:A:inc1", "provider:B:incB"}
    _fresh()
    resolved = {**SUMMARY, "incidents": []}

    def mixed(u):
        if u == URL_B:
            raise TimeoutError()
        return resolved
    engine.track_provider_incidents(*sp.incidents(fetch=mixed))
    assert {a["group"] for a in engine.get_alerts()} == {"provider:B:incB"}
    engine._active.clear()


def test_maintenance_stays_open_while_the_provider_verifies_it(monkeypatch):
    # shadow C1b: in_progress -> verifying keeps the alarm; completed ends it
    _fresh()
    engine._active.clear()
    maint = {"id": "m1", "name": "Planned work", "status": "in_progress", "impact": "maintenance",
             "components": [{"id": "c-ams", "name": "Amsterdam"}], "incident_updates": []}
    monkeypatch.setattr(sp, "outside_systems", lambda: [("Example", URL, {"c-ams": "ex-ams"})])
    for status, open_ in (("in_progress", True), ("verifying", True), ("completed", False)):
        _fresh()
        data = {**SUMMARY, "incidents": [], "scheduled_maintenances": [{**maint, "status": status}]}
        entries, read = sp.incidents(fetch=lambda u: data)
        engine.track_provider_incidents(entries, read)
        assert any(a["group"] == "provider:Example:m1" for a in engine.get_alerts()) is open_, status
        if status == "verifying":
            assert "being verified" in entries[0]["explanation"]["what"]
    engine._active.clear()


def test_maintenance_is_information_only_when_the_provider_shows_no_disruption(monkeypatch):
    # shadow P1 on #123: a disruptive maintenance must not drop to Information
    monkeypatch.setattr(sp, "outside_systems", lambda: [("Example", URL, {"c-ams": "ex-ams", "c-fra": "ex-fra"})])
    maint = {"id": "m1", "name": "Planned work", "status": "in_progress", "impact": "maintenance",
             "components": [{"id": "c-ams", "name": "Amsterdam"}], "incident_updates": []}
    quiet = {**maint, "impact": "none"}
    no_impact = {k: v for k, v in maint.items() if k != "impact"}
    cases = [(quiet, "info"),                                                              # explicit no impact
             (maint, "warning"),                    # impact "maintenance" may be planned unavailability
             (no_impact, "warning"),                                                # unknown is not "none"
             ({**maint, "impact": "major"}, "warning"),                                  # disruptive by impact
             ({**quiet, "components": [{"id": "c-fra", "name": "Frankfurt"}]}, "warning")]  # part in major outage
    for m, severity in cases:
        _fresh()
        data = {**SUMMARY, "incidents": [], "scheduled_maintenances": [m]}
        [e] = sp.incidents(fetch=lambda u: data)[0]
        assert e["severity"] == severity, m


def test_concurrent_first_reads_share_one_fetch():
    # shadow W1
    import threading
    from concurrent.futures import ThreadPoolExecutor
    _fresh()
    calls, gate = [], threading.Barrier(5, timeout=2)

    def fetch(u):
        calls.append(u)
        return SUMMARY

    def one(_):
        try:
            gate.wait()
        except threading.BrokenBarrierError:
            pass
        return sp.box({"url": URL, "component_id": "c-ams"}, fetch=fetch)
    with ThreadPoolExecutor(5) as ex:
        list(ex.map(one, range(5)))
    assert len(calls) == 1


def test_an_incident_keeps_every_part_it_names(monkeypatch):
    _fresh()
    engine._active.clear()
    two = {**SUMMARY, "incidents": [{**SUMMARY["incidents"][0],
                                     "components": [{"id": "c-fra", "name": "Frankfurt"}, {"id": "c-ams", "name": "Amsterdam"}]}]}
    monkeypatch.setattr(sp, "outside_systems", lambda: [("Example", URL, {"c-ams": "ex-ams", "c-fra": "ex-fra"})])
    engine.track_provider_incidents(*sp.incidents(fetch=lambda u: two))
    [a] = engine.get_alerts()
    assert a["explanation"]["affected_parts"] == ["ex-fra", "ex-ams"]
    engine._active.clear()


def test_a_provider_alarm_saved_in_the_old_key_format_keeps_its_report_and_ends(monkeypatch):
    # shadow: provider:<id> saved by #98 with a report, restored after a restart
    from src.models.alert import Alert
    _fresh()
    engine._active.clear()
    old = Alert(rule_id="provider_incident", kind="alarm", severity="critical", message="m",
                triggered_at="t", node_id="ex-fra", group="provider:inc1", title="Frankfurt unreachable",
                report={"status": "done", "executive_summary": "Existing report"})
    engine._active[("provider:inc1", "ex-fra")] = old
    engine.restore_alarms(engine.saved_alarms())
    monkeypatch.setattr(sp, "outside_systems", lambda: [("Example", URL, {"c-fra": "ex-fra"})])
    # still open: one alarm, under the new key, with its report
    engine.track_provider_incidents(*sp.incidents(fetch=lambda u: SUMMARY), part_provider=sp.part_providers())
    alarms = engine.get_alerts()
    assert [a["group"] for a in alarms] == ["provider:Example:inc1"]
    assert alarms[0]["report"]["executive_summary"] == "Existing report"
    # resolved by the provider: it ends
    _fresh()
    engine.track_provider_incidents(*sp.incidents(fetch=lambda u: {**SUMMARY, "incidents": []}),
                                    part_provider=sp.part_providers())
    assert engine.get_alerts() == []
    engine._active.clear()


def test_old_and_new_keys_for_one_incident_merge_without_losing_the_report():
    from src.models.alert import Alert
    engine._active.clear()
    mk = lambda group, report, first: Alert(rule_id="provider_incident", kind="alarm", severity="critical",
                                            message="m", triggered_at="t", node_id="ex-fra", group=group,
                                            report=report, first_seen=first)
    engine._active[("provider:inc1", "ex-fra")] = mk("provider:inc1", {"executive_summary": "Old report"}, "2026-11-07T20:00:00+00:00")
    engine._active[("provider:Example:inc1", "ex-fra")] = mk("provider:Example:inc1", None, "2026-11-07T21:00:00+00:00")
    engine._bind_legacy_provider_keys({"ex-fra": "Example"})
    [a] = engine.get_alerts()
    assert a["report"]["executive_summary"] == "Old report" and a["first_seen"].startswith("2026-11-07T20")
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
