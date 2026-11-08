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
    sr._reviews.clear(); sr._seen.clear(); sr._failed_at.clear(); sr._loaded[0] = False
    monkeypatch.setattr(ov, "ai_offline", lambda: None)
    monkeypatch.setattr(ov, "_outside_products", lambda: {"gh"})


def _run(cards, answer, now):
    with patch.object(ov, "system_cards", return_value=cards), \
         patch.object(ov, "call_model", return_value=(json.dumps({"summary": answer}), {})) as call:
        sr.refresh_due(now)
    return call


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
    demo = _user("viewer", "demo")
    with patch("src.api.routes.auth.verify_token", side_effect=demo), patch("src.api.routes.preferences.verify_token", side_effect=demo):
        assert c.put("/api/preferences/right-panel", json={"split": 0.3}).status_code == 403
