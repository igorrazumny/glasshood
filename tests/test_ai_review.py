# File: tests/test_ai_review.py
# Purpose: REQ-GHA-029 — the AI log review raises alarms; a critical one stays until a
# signed-in person acknowledges it; "Investigate deeper" writes a report that opens with an
# executive summary, saved with the alarm; a follow-up adds what happened since.

import json
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.rules.engine as eng
from src.analysis import ai_investigate, ai_review
from src.analysis import vertex_overview as ov
from src.api.routes.alerts import router
from src.models.topology import Node

LINE_1 = "2026-11-06T10:00:01 ERROR chat request failed: upstream timeout after 60s"
LINE_2 = "2026-11-06T10:05:12 ERROR chat request failed: upstream timeout after 60s"
LINE_OK = "2026-11-06T10:06:00 INFO request served in 120 ms"
TOPOLOGY = {"nodes": [], "edges": [{"source": "cv-mig", "target": "cv-db"}]}
PARTS = [({"id": "cv-mig", "label": "Confidential VM (MIG)", "status": "healthy"}, 'resource.type="gce_instance"'),
         ({"id": "cv-db", "label": "Database", "status": "healthy"}, 'resource.type="cloudsql_database"'),
         ({"id": "cv-public", "label": "Visitor", "status": "healthy"}, "")]


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    for s in (eng._active, eng._resolved, eng._rule_checked_at, eng._rule_names, eng._audit_log):
        s.clear()
    monkeypatch.setattr(ai_review, "STATE_DIR", "")
    monkeypatch.setattr(ai_review, "_saving", {"durable": False, "problem": None})
    monkeypatch.setattr(ov, "_walk_parts", lambda topology: iter(PARTS))
    monkeypatch.setattr(ov, "refresh_durable_spend", lambda: None)
    yield


def _review(answer, lines=(LINE_1, LINE_2, LINE_OK)):
    """One review run in which the model gives `answer`; returns what the model was sent."""
    sent = {}

    def model(prompt, text, max_tokens=600, search=False, deep=False):
        sent.update(json.loads(text))
        return json.dumps(answer), []
    with patch.object(ov, "_log_lines", side_effect=lambda flt, *a, **k: list(lines)), \
            patch.object(ov, "call_model", side_effect=model):
        ai_review.run(TOPOLOGY)
    return sent


def _problem(severity="warning", pid=None, part="cv-mig", evidence=(LINE_1,)):
    return {"problems": [{"id": pid, "part": part, "severity": severity,
                          "title": "Chat requests time out", "evidence": list(evidence)}]}


def _ai(alerts=None):
    return [a for a in (alerts or eng.get_alerts()) if a["kind"] == "ai"]


class TestReviewRaisesAlarms:
    def test_a_problem_in_the_logs_becomes_an_alarm_found_by_ai_review(self):
        sent = _review(_problem())
        [a] = _ai()
        assert a["title"] == "Confidential VM (MIG): Chat requests time out"
        assert a["node_id"] == "cv-mig" and a["severity"] == "warning"
        assert a["group"].startswith("ai:") and a["evidence"] == [LINE_1]
        # Only parts with a log location in the landscape file are read
        assert set(sent["logs"]) == {"cv-mig", "cv-db"}
        assert ai_review.status()["problems"] == 1 and ai_review.status()["error"] is None

    def test_nothing_real_gives_no_alarm(self):
        _review({"problems": []})
        assert _ai() == []

    def test_a_problem_without_a_log_line_behind_it_is_dropped(self):
        _review(_problem(evidence=["2026-11-06 ERROR something the logs never said"]))
        assert _ai() == []

    def test_a_problem_on_an_unknown_part_is_dropped(self):
        _review(_problem(part="not-a-part"))
        assert _ai() == []

    def test_the_same_problem_next_time_is_the_same_alarm(self):
        _review(_problem())
        [first] = _ai()
        _review(_problem(pid=first["group"][3:], evidence=(LINE_2,)))
        [again] = _ai()
        assert again["group"] == first["group"] and again["evidence"] == [LINE_2]

    def test_a_failed_review_says_why_and_keeps_the_alarms(self):
        _review(_problem())
        with patch.object(ov, "_log_lines", return_value=[LINE_1]), \
                patch.object(ov, "call_model", side_effect=ov.CapReached("daily cap of 1200 model calls reached")):
            ai_review.run(TOPOLOGY)
        assert len(_ai()) == 1
        assert "daily cap" in ai_review.status()["error"]


class TestCriticalStaysUntilAcknowledged:
    def test_a_warning_ends_when_no_longer_seen(self):
        _review(_problem("warning"))
        _review({"problems": []})
        assert _ai() == []
        assert [a["kind"] for a in eng.get_resolved()] == ["ai"]

    def test_a_critical_one_stays_even_when_the_next_review_does_not_see_it(self):
        _review(_problem("critical"))
        _review({"problems": []})
        _review({"problems": []})
        [a] = _ai()
        assert a["severity"] == "critical" and not a["acknowledged"]

    def test_once_acknowledged_it_ends_when_no_longer_seen_and_records_who(self):
        _review(_problem("critical"))
        [a] = _ai()
        assert eng.acknowledge_alert(a["group"], "cv-mig", "igor@example.com")
        [a] = _ai()
        assert a["acknowledged_by"] == "igor@example.com" and a["acknowledged_at"]
        _review({"problems": []})
        assert _ai() == []
        assert eng.get_resolved()[0]["acknowledged_by"] == "igor@example.com"

    def test_an_open_ai_alarm_never_gets_milder(self):
        _review(_problem("critical"))
        [a] = _ai()
        _review(_problem("warning", pid=a["group"][3:]))
        assert _ai()[0]["severity"] == "critical"

    def test_the_rule_check_does_not_end_ai_alarms(self):
        _review(_problem("warning"))
        eng.evaluate_rules([Node(id="other", label="Other", type="infra", status="healthy")], {}, rules_path="/nonexistent")
        with patch.object(eng, "_rules", return_value=[{"id": "x", "condition": {"metric": "cpu"}}]):
            eng.evaluate_rules([Node(id="other", label="Other", type="infra", status="healthy")], {})
        assert len(_ai()) == 1

    def test_ai_alarms_may_be_critical_unlike_examples(self):
        _review(_problem("critical"))
        assert _ai()[0]["severity"] == "critical"


class TestSavedAcrossRestart:
    def test_alarms_and_reports_come_back_after_a_restart(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ai_review, "STATE_DIR", str(tmp_path))
        _review(_problem("critical"))
        [a] = _ai()
        eng.set_report(a["group"], "cv-mig", {"status": "done", "executive_summary": "x"})
        ai_review.save()
        eng._active.clear()
        ai_review.load()
        [back] = _ai()
        assert back["group"] == a["group"] and back["report"]["executive_summary"] == "x"

    def test_without_a_state_folder_nothing_is_written(self, tmp_path):
        _review(_problem())
        ai_review.save()
        assert list(tmp_path.iterdir()) == []


REPORT = {"executive_summary": "Chat requests time out about every five minutes since 10:00.",
          "findings": [{"what": "Upstream timeouts", "evidence": [LINE_1, LINE_2]}],
          "what_is_happening": "The model server does not answer within 60 s.",
          "timeline": [{"time": "10:00", "event": "first timeout"}, {"time": "10:05", "event": "second"}],
          "pattern": "recurring", "pattern_explained": "Twice in five minutes.",
          "known_issue": "A common cause is an overloaded upstream.",
          "conclusion": "Ongoing upstream slowness.", "next_step": "Check the model server's load."}


def _investigate(answer=REPORT, search_fails=False):
    _review(_problem("critical"))
    [a] = _ai()
    calls = []

    def model(prompt, text, max_tokens=600, search=False, deep=False):
        calls.append({"search": search, "payload": json.loads(text)})
        if search and search_fails:
            raise RuntimeError("Vertex AI HTTP 400")
        return json.dumps(answer), ([{"title": "Known issue", "uri": "https://example.org/x"}] if search else [])
    with patch.object(ov, "_log_lines", side_effect=lambda flt, *a, **k: [LINE_1, LINE_2]), \
            patch.object(ov, "call_model", side_effect=model):
        why = ai_investigate.start(a["group"], "cv-mig", "igor@example.com", TOPOLOGY, run_async=False)
    return why, eng.find_alarm(a["group"], "cv-mig"), calls


class TestInvestigateDeeper:
    def test_the_report_opens_with_an_executive_summary_and_is_saved_with_the_alarm(self):
        why, alarm, calls = _investigate()
        assert why is None
        r = alarm["report"]
        assert r["status"] == "done" and r["executive_summary"].startswith("Chat requests")
        assert list(r)[:9] == ["executive_summary", "findings", "what_is_happening", "timeline", "pattern",
                               "pattern_explained", "known_issue", "conclusion", "next_step"]
        assert r["findings"][0]["evidence"] == [LINE_1, LINE_2]
        assert r["requested_by"] == "igor@example.com" and r["followups"] == []
        assert r["searched_web"] and r["sources"][0]["uri"] == "https://example.org/x"

    def test_it_reads_the_part_and_its_connected_parts_further_back(self):
        _, _, calls = _investigate()
        p = calls[0]["payload"]
        assert p["part_logs_24h"] and list(p["connected_parts_logs_24h"]) == ["Database"]

    def test_without_web_search_it_still_writes_the_report(self):
        _, alarm, calls = _investigate(search_fails=True)
        assert [c["search"] for c in calls] == [True, False]
        assert alarm["report"]["status"] == "done" and not alarm["report"]["searched_web"]

    def test_an_answer_without_summary_is_a_failed_report_that_says_why(self):
        _, alarm, _ = _investigate(answer={"findings": []})
        assert alarm["report"]["status"] == "failed" and "executive summary" in alarm["report"]["error"]


    def test_one_running_investigation_per_alarm(self):
        _review(_problem("critical"))
        [a] = _ai()
        eng.set_report(a["group"], "cv-mig", {"status": "running"})
        assert "already running" in ai_investigate.start(a["group"], "cv-mig", "u", TOPOLOGY, run_async=False)


class TestFollowUp:
    def test_a_follow_up_adds_what_happened_since(self):
        _, alarm, _ = _investigate()
        answer = {"summary": "This happened once more at 13:10 and not since.", "happened_again": True}
        with patch.object(ov, "_log_lines", return_value=[LINE_2]), \
                patch.object(ov, "call_model", return_value=(json.dumps(answer), [])):
            entry, why = ai_investigate.followup(alarm["group"], "cv-mig", "igor@example.com", TOPOLOGY)
        assert why is None and entry["happened_again"] and entry["by"] == "igor@example.com"
        saved = eng.find_alarm(alarm["group"], "cv-mig")["report"]
        assert saved["followups"][0]["summary"].startswith("This happened once more")
        assert saved["executive_summary"] == REPORT["executive_summary"]

    def test_no_follow_up_without_a_finished_report(self):
        _review(_problem())
        [a] = _ai()
        entry, why = ai_investigate.followup(a["group"], "cv-mig", "u", TOPOLOGY)
        assert entry is None and "no finished report" in why


def _client(role="operator"):
    app = FastAPI()
    app.include_router(router)

    def auth(request):
        request.state.user_context = {"user": "igor@example.com", "role": role}
    return app, auth


class TestRoutes:
    def test_acknowledge_records_the_signed_in_user_not_the_name_sent(self):
        _review(_problem("critical"))
        [a] = _ai()
        app, auth = _client()
        with patch("src.api.routes.alerts.verify_token", side_effect=auth), \
                patch("src.api.routes.alerts.require_role"):
            r = TestClient(app).post("/api/alerts/ack", json={"rule_id": a["group"], "node_id": "cv-mig",
                                                              "user": "someone else"})
        assert r.status_code == 200
        assert _ai()[0]["acknowledged_by"] == "igor@example.com"

    def test_investigate_and_read_the_report_back(self):
        _review(_problem("critical"))
        [a] = _ai()
        app, auth = _client()
        with patch("src.api.routes.alerts.verify_token", side_effect=auth), \
                patch("src.api.routes.alerts.require_role"), \
                patch("src.api.routes.topology.get_topology_data", return_value=TOPOLOGY), \
                patch.object(ai_investigate.threading, "Thread") as thread:
            c = TestClient(app)
            r = c.post("/api/alerts/investigate", json={"group": a["group"], "node_id": "cv-mig"})
            assert r.status_code == 202 and thread.called
            again = c.post("/api/alerts/investigate", json={"group": a["group"], "node_id": "cv-mig"})
            assert again.status_code == 409
            one = c.get("/api/alerts/one", params={"group": a["group"], "node_id": "cv-mig"}).json()
        assert one["report"]["status"] == "running" and one["report"]["requested_by"] == "igor@example.com"
        assert one["can_act"] is True

    def test_a_viewer_cannot_investigate(self):
        from fastapi import HTTPException
        _review(_problem())
        [a] = _ai()
        app, auth = _client("viewer")

        def deny(request, role):
            raise HTTPException(status_code=403, detail="no")
        with patch("src.api.routes.alerts.verify_token", side_effect=auth), \
                patch("src.api.routes.alerts.require_role", side_effect=deny):
            c = TestClient(app)
            r = c.post("/api/alerts/investigate", json={"group": a["group"], "node_id": "cv-mig"})
            one = c.get("/api/alerts/one", params={"group": a["group"], "node_id": "cv-mig"}).json()
        assert r.status_code == 403 and one["can_act"] is False
        assert eng.find_alarm(a["group"], "cv-mig")["report"] is None


class TestWebSearchIsReportedTruly:
    def test_a_search_that_returned_nothing_is_not_called_a_web_search(self):
        _review(_problem("critical"))
        [a] = _ai()
        with patch.object(ov, "_log_lines", return_value=[LINE_1]), \
                patch.object(ov, "call_model", return_value=(json.dumps(REPORT), [])):
            ai_investigate.start(a["group"], "cv-mig", "u", TOPOLOGY, run_async=False)
        assert eng.find_alarm(a["group"], "cv-mig")["report"]["searched_web"] is False

    def test_the_searches_made_are_kept_even_without_page_links(self, monkeypatch):
        class Resp:
            status_code = 200

            def json(self):
                return {"candidates": [{"content": {"parts": [{"text": "{}"}]},
                                        "groundingMetadata": {"webSearchQueries": ["envoy reset reason"],
                                                              "groundingChunks": [{"web": {"uri": "javascript:x"}}]}}],
                        "usageMetadata": {}}
        monkeypatch.setattr(ov, "_reserve_call", lambda: None)
        monkeypatch.setattr(ov, "_headers", lambda: {})
        monkeypatch.setattr(ov, "_record_usage", lambda usage: None)
        monkeypatch.setattr(ov.httpx, "post", lambda *a, **k: Resp())
        _, sources = ov.call_model("p", "t", search=True)
        assert sources == [{"query": "envoy reset reason"}]  # a non-https link is dropped


class TestReviewC1Persistence:
    def test_without_a_state_folder_the_status_says_a_restart_drops_alarms(self):
        ai_review.load()
        st = ai_review.status()
        assert st["saved"] is False and "restart drops" in st["saving_problem"]

    def test_an_unwritable_folder_is_reported_not_silent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ai_review, "STATE_DIR", str(tmp_path / "missing"))
        _review(_problem("critical"))
        assert ai_review.save() is False
        assert "saving failed" in ai_review.status()["saving_problem"]

    def test_a_report_on_an_ordinary_alarm_survives_a_restart(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ai_review, "STATE_DIR", str(tmp_path))
        eng.track_findings([{"id": "drift", "text": "Config drift", "part": "cv-mig"}], [])
        [f] = eng.get_alerts()
        assert eng.set_report(f["group"], "cv-mig", {"status": "done", "executive_summary": "drift report"})
        ai_review.save()
        eng._active.clear()
        ai_review.load()
        back = eng.find_alarm(f["group"], "cv-mig")
        assert back["kind"] == "observation" and back["report"]["executive_summary"] == "drift report"
        # The next check of that finding updates it and keeps the report
        eng.track_findings([{"id": "drift", "text": "Config drift", "part": "cv-mig"}], [])
        assert eng.find_alarm(f["group"], "cv-mig")["report"]["executive_summary"] == "drift report"

    def test_an_unacknowledged_critical_survives_a_restart(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ai_review, "STATE_DIR", str(tmp_path))
        _review(_problem("critical"))
        eng._active.clear()
        ai_review.load()
        [a] = _ai()
        assert a["severity"] == "critical" and not a["acknowledged"]
        assert ai_review.status()["saved"] is True

    def test_an_unreadable_saved_file_is_left_as_it_is(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ai_review, "STATE_DIR", str(tmp_path))
        (tmp_path / ai_review._STATE_FILE).write_text("{not json")
        monkeypatch.setattr(ai_review, "_saving", {"durable": False, "problem": None})
        ai_review.load()
        _review(_problem("critical"))
        assert (tmp_path / ai_review._STATE_FILE).read_text() == "{not json"
        assert "could not be read" in ai_review.status()["saving_problem"]


class TestReviewC2EvidenceIntegrity:
    def test_a_quote_the_model_was_not_shown_is_never_published_as_evidence(self):
        answer = dict(REPORT, findings=[{"what": "Data lost", "evidence": ["FABRICATED LINE NOT IN INPUT"]},
                                        {"what": "Upstream timeouts", "evidence": [LINE_1, "ALSO MADE UP"]}])
        _, alarm, _ = _investigate(answer=answer)
        found = alarm["report"]["findings"]
        assert found[0] == {"what": "Data lost", "evidence": [], "backed_by_logs": False}
        assert found[1]["evidence"] == [LINE_1] and found[1]["backed_by_logs"] is True
        assert alarm["report"]["quotes_not_in_logs_dropped"] == 2
        assert "FABRICATED" not in json.dumps(alarm["report"])


def _explained(**extra):
    p = _problem("critical")
    p["problems"][0].update({"what": "Chat answers fail for users because the server times out.",
                             "suspicion": "Likely the model provider is slow to answer.",
                             "directions": ["Possibly the network to the provider.", "", 7]}, **extra)
    return p


class TestPlainExplanation:
    """REQ-GHA-031: the alarm carries a plain explanation, written when it is raised."""

    def test_the_alarm_says_what_is_wrong_the_suspicion_and_where_to_look(self):
        _review(_explained())
        [a] = _ai()
        assert a["explanation"] == {"what": "Chat answers fail for users because the server times out.",
                                    "suspicion": "Likely the model provider is slow to answer.",
                                    "directions": ["Possibly the network to the provider."]}
        assert a["evidence"] == [LINE_1]  # the log lines stay behind it as evidence

    def test_the_prompt_asks_for_hedged_causes_never_facts(self):
        assert '"suspicion"' in ai_review.REVIEW_PROMPT and "never state a cause as a fact" in ai_review.REVIEW_PROMPT

    def test_without_a_what_there_is_no_explanation_but_the_alarm_stands(self):
        _review(_problem("warning"))
        [a] = _ai()
        assert a["explanation"] is None and a["title"]

    def test_a_later_review_without_explanation_keeps_the_earlier_one(self):
        _review(_explained())
        [a] = _ai()
        _review(_problem("critical", pid=a["group"][3:]))
        [again] = _ai()
        assert again["explanation"]["what"].startswith("Chat answers fail")

    def test_the_explanation_survives_a_restart(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ai_review, "STATE_DIR", str(tmp_path))
        _review(_explained())
        eng._active.clear()
        ai_review.load()
        [back] = _ai()
        assert back["explanation"]["suspicion"] == "Likely the model provider is slow to answer."

    def test_explanation_texts_are_bounded_plain_strings(self):
        _review(_explained(what="x" * 5000, directions=["a", "b", "c", "d"]))
        [a] = _ai()
        assert len(a["explanation"]["what"]) == 800 and a["explanation"]["directions"] == ["a", "b", "c"]

    def test_one_review_call_writes_it_no_call_when_opening(self):
        calls = []
        with patch.object(ov, "_log_lines", side_effect=lambda *a, **k: [LINE_1]), \
                patch.object(ov, "call_model", side_effect=lambda *a, **k: calls.append(1) or (json.dumps(_explained()), [])):
            ai_review.run(TOPOLOGY)
        [a] = _ai()
        app, auth = _client()
        with patch("src.api.routes.alerts.verify_token", side_effect=auth), \
                patch.object(ov, "call_model", side_effect=AssertionError("no model call on opening")):
            one = TestClient(app).get("/api/alerts/one", params={"group": a["group"], "node_id": "cv-mig"}).json()
        assert len(calls) == 1 and one["explanation"]["what"].startswith("Chat answers fail")


class TestLandscapeName:
    """REQ-GHA-031 clause 5: a discovered server is named by its box on the landscape."""

    def test_a_server_inside_a_group_is_named_by_the_group(self, monkeypatch):
        monkeypatch.setattr(ov, "_manifest_info", lambda: ({}, {"cv-mig": "Confidential VM (MIG)"}))
        topo = {"nodes": [{"id": "vm-coldvault-mig-xjxr", "label": "coldvault-mig-xjxr",
                           "metrics": {"_parent": "cv-mig"}},
                          {"id": "cv-db", "label": "Database"}]}
        assert ai_review.landscape_names(topo) == {"vm-coldvault-mig-xjxr": "Confidential VM (MIG)"}

    def test_the_alarm_title_uses_the_landscape_name(self, monkeypatch):
        monkeypatch.setattr(ov, "_manifest_info", lambda: ({}, {"cv-mig": "Confidential VM (MIG)"}))
        parts = [({"id": "vm-x", "label": "coldvault-mig-xjxr", "status": "healthy"}, 'resource.type="gce_instance"')]
        monkeypatch.setattr(ov, "_walk_parts", lambda topology: iter(parts))
        topo = {"nodes": [{"id": "vm-x", "label": "coldvault-mig-xjxr", "metrics": {"_parent": "cv-mig"}}], "edges": []}
        with patch.object(ov, "_log_lines", side_effect=lambda *a, **k: [LINE_1]), \
                patch.object(ov, "call_model", side_effect=lambda *a, **k: (json.dumps(_problem(part="vm-x")), [])):
            ai_review.run(topo)
        [a] = _ai()
        assert a["title"] == "Confidential VM (MIG): Chat requests time out"
        assert "coldvault-mig-xjxr" not in a["title"]


def test_an_acknowledged_ai_alarm_on_a_part_that_is_gone_ends():
    from src.models.alert import Alert
    from src.models.topology import Node
    from unittest.mock import patch as _patch
    eng._active.clear()
    a = Alert(rule_id="ai_review", kind="ai", severity="critical", message="m", triggered_at="t",
              node_id="vm-old", group="ai:x", first_seen="2026-11-07T11:52:48+00:00")
    eng._active[("ai:x", "vm-old")] = a
    rule = {"id": "node_error", "group": "status", "severity": "critical", "scope": "node",
            "condition": {"metric": "status", "operator": "==", "value": "error"}}
    with _patch.object(eng, "_rules", lambda path: [rule]):
        eng.evaluate_rules([Node(id="vm-new", label="new", type="vm", status="healthy")], {})
        assert ("ai:x", "vm-old") in eng._active          # unacknowledged critical waits for a person
        eng.acknowledge_alert("ai:x", "vm-old", "admin@example.com")
        eng.evaluate_rules([Node(id="vm-new", label="new", type="vm", status="healthy")], {})
    assert ("ai:x", "vm-old") not in eng._active
    assert eng.get_resolved()[0]["acknowledged_by"] == "admin@example.com"
    eng._active.clear()
