"""REQ-GHA-046 clauses 4, 5, 11, 15 and 16."""
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.analysis import selection_review as sr
from src.analysis import vertex_overview as ov
from src.api.server import app


def _rec(cond="normal", at=1.0, alerts=()):
    return {"summary": "text", "condition": cond, "analyzed_at": at, "alerts": list(alerts)}


@pytest.fixture(autouse=True)
def clean(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_STATE_DIR", str(tmp_path))
    sr._reviews.clear(); sr._seen.clear(); sr._failed_at.clear(); sr._loaded[0] = False; sr._unsaved[0] = False; sr.problem[0] = None
    monkeypatch.setattr(ov, "ai_offline", lambda: None)
    monkeypatch.setattr(ov, "_outside_products", lambda: {"gh"})
    monkeypatch.setattr(sr, "_names", lambda: {"a": "Alpha", "gh": "GitHub"})


def _run(cards, answer, now):
    with patch.object(ov, "system_cards", return_value=cards), \
         patch.object(ov, "call_model", return_value=(json.dumps(_answer(answer)), {})) as call:
        sr.refresh_due(now)
    return call


def _answer(summary, **more):
    return {"summary": summary, "score": 7, "issues": [], "recommendations": [], **more}


def test_written_only_after_settling_and_only_on_change():
    cards = {"a": _rec(), "gh": _rec()}
    assert _run(cards, "All fine.", 0).call_count == 0
    assert _run(cards, "All fine.", 100).call_count == 3
    assert sr.get_reviews()["all"]["summary"] == "All fine."
    assert _run(cards, "All fine.", 400).call_count == 0


def test_groups_see_only_their_systems():
    with patch.object(ov, "system_cards", return_value={"a": _rec(), "gh": _rec()}), \
         patch.object(ov, "call_model", return_value=('{"summary": "x"}', {})) as call:
        sr.refresh_due(0); sr.refresh_due(100)
    assert sorted(len(json.loads(c.args[1])) for c in call.call_args_list) == [1, 1, 2]


def test_observations_never_reach_the_model():
    notes = [{"kind": "observation", "severity": "warning", "title": "firewall", "rule_id": "x"},
             {"kind": "alarm", "severity": "warning", "title": "leftover", "rule_id": "finding:fw"},
             {"kind": "alarm", "severity": "info", "title": "note", "rule_id": "y"},
             {"kind": "alarm", "severity": "critical", "title": "backend down", "rule_id": "z"}]
    assert sr._real_alerts(_rec(alerts=notes)) == ["backend down"]


def test_a_list_is_refused_and_the_last_good_review_kept():
    _run({"a": _rec()}, "Fine.", 0); _run({"a": _rec()}, "Fine.", 100)
    cards = {"a": _rec(at=2.0)}
    _run(cards, "- one\n- two", 200); _run(cards, "- one\n- two", 300)
    assert sr.get_reviews()["all"]["summary"] == "Fine."


def test_survives_a_restart():
    cards = {"a": _rec()}
    _run(cards, "Fine.", 0); _run(cards, "Fine.", 100)
    sr._reviews.clear(); sr._loaded[0] = False
    assert _run(cards, "Other.", 500).call_count == 0
    assert sr.get_reviews()["all"]["summary"] == "Fine."


def _user(role, name):
    def f(request):
        request.state.user_context = {"user": name, "role": role, "customer_id": ""}
        return request.state.user_context
    return f


def test_boundary_is_per_account_and_refused_for_the_demo_role():
    c = TestClient(app, raise_server_exceptions=False)
    op = _user("operator", "a@x")
    with patch("src.api.routes.auth.verify_token", side_effect=op), patch("src.api.routes.preferences.verify_token", side_effect=op):
        assert c.put("/api/preferences/right-panel", json={"split": 0.3}).status_code == 200
        assert c.get("/api/preferences/right-panel").json()["split"] == 0.3
    other = _user("operator", "b@x")
    with patch("src.api.routes.preferences.verify_token", side_effect=other):
        assert c.get("/api/preferences/right-panel").json()["split"] is None
    reader = _user("viewer", "reader@x")
    with patch("src.api.routes.auth.verify_token", side_effect=reader), patch("src.api.routes.preferences.verify_token", side_effect=reader):
        assert c.put("/api/preferences/right-panel", json={"split": 0.4}).status_code == 200
    demo = _user("viewer", "demo@glasshood.example.com")
    with patch("src.api.routes.auth.verify_token", side_effect=demo), patch("src.api.routes.preferences.verify_token", side_effect=demo):
        assert c.put("/api/preferences/right-panel", json={"split": 0.3}).status_code == 403


def test_a_review_of_older_records_says_so():
    cards = {"a": _rec()}
    _run(cards, "Fine.", 0); _run(cards, "Fine.", 100)
    newer = {"a": _rec("failing", at=2.0)}
    with patch.object(ov, "system_cards", return_value=newer):
        got = sr.get_reviews()["all"]
    assert got["summary"] == "Fine." and got["current"] is False and got["update_failed"] is False
    _run(newer, "- x", 200); _run(newer, "- x", 300)
    with patch.object(ov, "system_cards", return_value=newer):
        assert sr.get_reviews()["all"]["update_failed"] is True


def test_the_review_has_the_single_system_shape_on_the_stronger_model():
    cards = {"a": _rec("attention", alerts=[{"kind": "alarm", "severity": "critical", "title": "backend down", "rule_id": "z"}])}
    answer = {"score": 6, "summary": "A is degraded.", "issues": ["A: one of two backends is down."],
              "recommendations": ["Restore A's second backend.", "b", "c", "d"]}
    with patch.object(ov, "system_cards", return_value=cards), \
         patch.object(ov, "call_model", return_value=(json.dumps(answer), {})) as call:
        sr.refresh_due(0); sr.refresh_due(100)
    assert call.call_args.kwargs.get("deep") is True
    with patch.object(ov, "system_cards", return_value=cards):
        got = sr.get_reviews()["all"]
    assert (got["score"], got["summary"], got["issues"], len(got["recommendations"])) == (6, "A is degraded.", ["A: one of two backends is down."], 3)


@pytest.mark.parametrize("answer", [
    _answer("ColdVault has leftover firewall rules."),
    _answer("Fine.", issues=["Several parts are not checked."]),
    _answer("Fine.", issues="text"),
    _answer("Fine.", issues=["A is down."], recommendations=["- do this"]),
    {"summary": "Fine.", "issues": [], "recommendations": []},
    _answer("Fine.", score=99),
    _answer("Fine.", score=True),
    _answer("Fine.", score=7.5),
    _answer("The services are operating normally.", score=9, recommendations=["Restart ColdVault."]),
    _answer("ColdVault has no operational fault, but it carries configuration and security follow-up items."),
    _answer("Fine; some cleanup is outstanding on ColdVault."),
])
def test_notes_and_malformed_answers_are_refused(answer):
    cards = {"a": _rec()}
    _run(cards, "Fine.", 0); _run(cards, "Fine.", 100)
    newer = {"a": _rec(at=2.0)}
    with patch.object(ov, "system_cards", return_value=newer), \
         patch.object(ov, "call_model", return_value=(json.dumps(answer), {})):
        sr.refresh_due(200); sr.refresh_due(300)
    with patch.object(ov, "system_cards", return_value=newer):
        got = sr.get_reviews()["all"]
    assert got["summary"] == "Fine." and got["update_failed"] is True


def test_the_model_gets_display_names_and_each_system_s_attention_items():
    cards = {"a": {**_rec("attention"), "issues": ["Backend: 1 of 2 healthy"]}}
    with patch.object(ov, "system_cards", return_value=cards), \
         patch.object(ov, "call_model", return_value=(json.dumps(_answer("x", score=6, issues=["Alpha: one backend is down."])), {})) as call:
        sr.refresh_due(0); sr.refresh_due(100)
    sent = json.loads(call.call_args.args[1])
    assert sent[0]["system"] == "Alpha" and sent[0]["needs_attention"] == ["Backend: 1 of 2 healthy"]


def test_systems_are_called_by_their_display_names_whatever_case_the_model_used():
    names = {"coldvault": "ColdVault", "glasshood": "GlassHood"}
    assert sr._as_named("coldvault and Glasshood are fine; coldvault.ai answers; GLASSHOOD too.", names) \
        == "ColdVault and GlassHood are fine; coldvault.ai answers; GlassHood too."
    assert sr._as_named("A part of it is fine.", {"a": "Alpha"}) == "A part of it is fine."
    assert sr._as_named("The affected system is coldvault. coldvault-mig stays.", names) == "The affected system is ColdVault. coldvault-mig stays."
    cards = {"a": _rec()}
    with patch.object(ov, "system_cards", return_value=cards), \
         patch.object(ov, "call_model", return_value=(json.dumps(_answer("alpha is operating normally.", score=9)), {})):
        sr.refresh_due(0); sr.refresh_due(100)
    with patch.object(ov, "system_cards", return_value=cards):
        assert sr.get_reviews()["all"]["summary"] == "Alpha is operating normally."


def test_a_success_clears_an_earlier_failed_attempt():
    cards = {"a": _rec()}
    with patch.object(ov, "system_cards", return_value=cards), \
         patch.object(ov, "call_model", return_value=('{"summary": ["bad"]}', {})):
        sr.refresh_due(0); sr.refresh_due(100)
    with patch.object(ov, "system_cards", return_value=cards):
        assert sr.get_reviews()["all"]["update_failed"] is True
    _run(cards, "Fine.", 800)
    with patch.object(ov, "system_cards", return_value=cards):
        got = sr.get_reviews()["all"]
    assert got["summary"] == "Fine." and got["update_failed"] is False and got["current"] is True


def test_an_external_system_gives_only_its_condition_score_and_assessment():
    cards = {"gh": {**_rec("attention"), "issues": ["Component X degraded"],
                    "alerts": [{"kind": "alarm", "severity": "warning", "title": "Incident 1", "rule_id": "provider_incident"}]}}
    with patch.object(ov, "system_cards", return_value=cards), \
         patch.object(ov, "call_model", return_value=(json.dumps(_answer("GitHub is degraded.", score=5, issues=["GitHub reports degraded service."])), {})) as call:
        sr.refresh_due(0); sr.refresh_due(100)
    sent = json.loads(call.call_args.args[1])[0]
    assert sent["system"] == "GitHub" and "needs_attention" not in sent and "alerts" not in sent


def test_an_external_system_s_trouble_is_one_issue():
    cards = {"gh": _rec("attention")}
    answer = _answer("GitHub is degraded.", score=5, issues=["GitHub: Actions degraded.", "GitHub: Pages outage in one region."])
    with patch.object(ov, "system_cards", return_value=cards), \
         patch.object(ov, "call_model", return_value=(json.dumps(answer), {})):
        sr.refresh_due(0); sr.refresh_due(100)
    assert not _reviews_with_text()


@pytest.mark.parametrize("with_provider", [False, True])
def test_internal_faults_through_a_shared_provider_are_not_the_provider_s_issues(monkeypatch, with_provider):
    monkeypatch.setattr(sr, "_names", lambda: {"a": "Alpha", "b": "Beta", "gh": "GitHub"})
    cards = {"a": _rec("attention"), "b": _rec("attention"), **({"gh": _rec("attention")} if with_provider else {})}
    issues = ["Alpha requests time out through GitHub.", "Beta login fails through GitHub."] + \
        (["GitHub reports degraded service."] if with_provider else [])
    answer = _answer("Two systems fail through GitHub.", score=4, issues=issues)
    with patch.object(ov, "system_cards", return_value=cards), \
         patch.object(ov, "call_model", return_value=(json.dumps(answer), {})):
        sr.refresh_due(0); sr.refresh_due(100)
    with patch.object(ov, "system_cards", return_value=cards):
        got = sr.get_reviews()["all"]
    assert got["issues"] == issues and got["current"] is True and got["update_failed"] is False


def test_an_issue_that_names_no_fault_is_left_out_and_the_review_kept():
    cards = {"a": _rec("attention")}
    answer = _answer("Alpha has no operational fault.", score=8,
                     issues=["Alpha has no operational fault in this review.", "Alpha needs attention."],
                     recommendations=["Review Alpha."])
    with patch.object(ov, "system_cards", return_value=cards), \
         patch.object(ov, "call_model", return_value=(json.dumps(answer), {})):
        sr.refresh_due(0); sr.refresh_due(100)
    with patch.object(ov, "system_cards", return_value=cards):
        got = sr.get_reviews()["all"]
    assert got["summary"] == "Alpha has no operational fault." and got["issues"] == [] and got["recommendations"] == []
    assert got["current"] is True and got["update_failed"] is False


def test_a_step_for_a_left_out_item_goes_with_it(monkeypatch):
    monkeypatch.setattr(sr, "_names", lambda: {"a": "ColdVault", "gh": "Cloudflare"})
    cards = {"a": _rec("normal"), "gh": _rec("attention")}
    answer = _answer("Cloudflare is degraded; ColdVault is operating normally.", score=6,
                     issues=["ColdVault has no operational fault.", "Cloudflare reports degraded service."],
                     recommendations=["Restart ColdVault.", "Follow Cloudflare status updates."])
    with patch.object(ov, "system_cards", return_value=cards), \
         patch.object(ov, "call_model", return_value=(json.dumps(answer), {})):
        sr.refresh_due(0); sr.refresh_due(100)
    with patch.object(ov, "system_cards", return_value=cards):
        got = sr.get_reviews()["all"]
    assert got["issues"] == ["Cloudflare reports degraded service."]
    assert got["recommendations"] == ["Follow Cloudflare status updates."]


def test_the_diff_names_the_previous_check():
    from src.discovery import diff
    from src.models.topology import Node
    diff._previous_snapshot = None
    with patch.object(diff.time, "time", side_effect=[100.0, 200.0]):
        first = diff.update_snapshot([Node(id="a", label="a", type="vm", status="healthy")])
        second = diff.update_snapshot([Node(id="a", label="a", type="vm", status="error")])
    assert first["previous_at"] is None
    assert second["previous_at"] == 100.0 and second["changed"][0]["id"] == "a"


def test_reviews_of_an_older_shape_are_set_aside_and_written_again(tmp_path):
    (tmp_path / "ai_selection.json").write_text(json.dumps(
        {"all": {"summary": "ColdVault has leftover firewall findings.", "analyzed_at": 1.0, "sig": "a:1.0:normal"}}))
    cards = {"a": _rec()}
    with patch.object(ov, "system_cards", return_value=cards):
        assert sr.get_reviews().get("all", {}).get("summary") is None
    assert _run(cards, "Fine.", 0).call_count == 0
    assert _run(cards, "Fine.", 100).call_count == 2   # all systems and the internal group; no external record
    saved = json.loads((tmp_path / "ai_selection.json").read_text())
    assert saved["all"]["summary"] == "Fine." and saved["all"]["shape"] == sr.SHAPE


def test_a_list_in_json_is_refused():
    cards = {"a": _rec()}
    with patch.object(ov, "system_cards", return_value=cards), \
         patch.object(ov, "call_model", return_value=('{"summary": ["one", "two"]}', {})):
        sr.refresh_due(0); sr.refresh_due(100)
    assert "all" not in {k for k, v in _reviews_with_text().items()}


def _reviews_with_text():
    return {k: v for k, v in sr._reviews.items() if v.get("summary")}


def test_failed_save_is_reported_and_retried_without_a_new_call():
    cards = {"a": _rec()}
    with patch("src.analysis.selection_review.os.replace", side_effect=OSError):
        _run(cards, "Fine.", 0); _run(cards, "Fine.", 100)
    assert sr.problem[0]
    assert _run(cards, "Other.", 200).call_count == 0
    assert sr.problem[0] is None
    sr._reviews.clear(); sr._loaded[0] = False
    with patch.object(ov, "system_cards", return_value=cards):
        assert sr.get_reviews()["all"]["summary"] == "Fine."


def test_a_failed_read_is_retried_before_anything_is_regenerated():
    cards = {"a": _rec()}
    _run(cards, "Fine.", 0); _run(cards, "Fine.", 100)
    sr._reviews.clear(); sr._loaded[0] = False
    with patch("builtins.open", side_effect=OSError):
        assert _run(cards, "Other.", 200).call_count == 0
    assert sr.problem[0]
    assert _run(cards, "Other.", 400).call_count == 0
    assert sr.problem[0] is None
    with patch.object(ov, "system_cards", return_value=cards):
        assert sr.get_reviews()["all"]["summary"] == "Fine."


@pytest.mark.parametrize("login", ["demo@glasshood.example.com", "DEMO@GLASSHOOD.EXAMPLE.COM", "Demo@GlassHood.Example.Com"])
def test_every_spelling_of_the_demo_login_is_refused(login):
    c = TestClient(app, raise_server_exceptions=False)
    with patch("src.api.routes.auth.GLASSHOOD_PASSWORD", "not-the-demo-one"):
        token = c.post("/api/auth/login", json={"login": login, "password": "demo"}).json()["token"]
    r = c.put("/api/preferences/right-panel", json={"split": 0.3}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403
    assert not (__import__("pathlib").Path(__import__("os").environ["AI_STATE_DIR"]) / "ui_prefs.json").exists()
