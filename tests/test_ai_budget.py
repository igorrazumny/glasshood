# File: tests/test_ai_budget.py
# Purpose: REQ-GHA-041 — monthly per-provider limits, the move to the backup and its alarms

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.analysis import ai_budget as b, vertex_overview as ov
from src.rules import engine


def ok():
    return SimpleNamespace(status_code=200, json=lambda: {"output": [{"type": "message", "content": [{"type": "output_text", "text": "{}"}]}],
                                                          "usage": {"input_tokens": 1000, "output_tokens": 100}})


def fail(status, code=""):
    return SimpleNamespace(status_code=status, json=lambda: {"error": {"code": code, "type": code}})


def claude():
    return SimpleNamespace(stop_reason="end_turn", usage=SimpleNamespace(input_tokens=1000, output_tokens=100),
                           content=[SimpleNamespace(type="text", text="{}")])


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(ov, "PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("AI_STATE_DIR", str(tmp_path))
    b._unsaved.clear(); b._logged.clear(); b._lines.clear()
    with ov._lock:
        ov._spend.clear(); ov._spend.update(ov._new_day())
    ov.refresh_durable_spend()
    with patch("anthropic.Anthropic") as client:
        client.return_value.messages.create.return_value = claude()
        yield SimpleNamespace(path=tmp_path, claude=client)


def spend(world, provider, usd):
    b.charge(provider, usd)


def test_the_number_of_calls_blocks_nothing(world, monkeypatch):
    monkeypatch.setattr(ov, "DAILY_CALL_CAP", 1)
    with patch("httpx.post", return_value=ok()):
        ov.call_model("s", "{}"); ov.call_model("s", "{}"); ov.call_model("s", "{}")
    assert ov.get_spend()["calls"] == 3


def test_each_answer_counts_toward_its_own_provider_and_survives(world):
    with patch("httpx.post", return_value=ok()):
        ov.call_model("s", "{}")
    saved = json.loads((world.path / "ai_budget.json").read_text())
    assert saved["openai"]["cost"] > 0 and saved["anthropic"]["cost"] == 0
    assert b.status()["openai"]["spent"] == pytest.approx(saved["openai"]["cost"], abs=1e-4)


def test_at_the_limit_the_main_provider_gets_no_call_and_the_backup_answers(world):
    spend(world, "openai", 20)
    with patch("httpx.post", side_effect=AssertionError("no call to the main provider")):
        text, _ = ov.call_model("s", "{}")
    assert text == "{}"
    assert b.status()["anthropic"]["spent"] > 0


def test_the_limit_is_configuration(world, monkeypatch):
    spend(world, "openai", 20)
    monkeypatch.setenv("OPENAI_MONTHLY_LIMIT_USD", "50")
    assert b.gate("openai") is None


@pytest.mark.parametrize("response,words", [(fail(401), "API key"), (fail(429, "insufficient_quota"), "credit or quota")])
def test_a_refusal_about_the_account_moves_to_the_backup(world, response, words):
    with patch("httpx.post", return_value=response):
        ov.call_model("s", "{}")
    assert words in b.status()["openai"]["blocked"]
    with patch("httpx.post", return_value=ok()):
        ov.call_model("s", "{}")
    assert b.status()["openai"]["blocked"] is None     # it answered again


def test_an_ordinary_overload_is_not_a_block(world):
    with patch("httpx.post", return_value=fail(429, "rate_limit_exceeded")):
        ov.call_model("s", "{}")
    assert b.status()["openai"]["blocked"] is None


def test_totals_that_cannot_be_read_block_the_provider(world):
    (world.path / "ai_budget.json").write_text("{broken")
    assert "could not be read" in b.gate("openai")
    assert b.alarms()


def test_both_blocked_makes_no_call_and_says_so(world):
    spend(world, "openai", 20); spend(world, "anthropic", 20)
    with patch("httpx.post", side_effect=AssertionError("no call")), pytest.raises(ov.CapReached):
        ov.call_model("s", "{}")
    world.claude.return_value.messages.create.assert_not_called()
    [alarm] = b.alarms()
    assert alarm["group"] == "budget:all" and "resume" in alarm["explanation"]["what"]


def test_web_search_says_plainly_it_needs_the_main_provider(world):
    spend(world, "openai", 20)
    with patch("httpx.post", side_effect=AssertionError("no call")), pytest.raises(ov.CapReached, match="web search"):
        ov.call_model("s", "{}", search=True, deep=True)


def test_alarm_says_what_and_ends_by_itself(world, monkeypatch):
    with engine._lock:
        engine._active.clear()
    assert b.alarms() == []
    spend(world, "openai", 20)
    ov._sync_budget_alarms()
    [a] = [x for x in engine.get_alerts() if x["rule_id"] == "ai_budget"]
    assert a["severity"] == "critical" and "backup" in a["title"] and "$20.00" in a["explanation"]["what"]
    assert ov.system_cards()["glasshood"]["critical_notice"]
    monkeypatch.setenv("OPENAI_MONTHLY_LIMIT_USD", "50")
    ov._sync_budget_alarms()
    assert not [x for x in engine.get_alerts() if x["rule_id"] == "ai_budget"]


def test_a_block_is_logged_in_words_once_an_hour_and_reaches_the_log_review(world):
    spend(world, "openai", 20)
    with patch("httpx.post"):
        ov.call_model("s", "{}"); ov.call_model("s", "{}")
    lines = b.recent_lines()
    assert len(lines) == 2
    assert "OpenAI is blocked" in lines[0] and "backup" in lines[1]
    from src.analysis import ai_review
    seen = {}

    def model(prompt, text, **k):
        seen.update(json.loads(text))
        return json.dumps({"problems": []}), []
    part = {"id": b.ALARM_PART, "label": "AI", "status": "healthy"}
    with patch.object(ov, "_walk_parts", return_value=[(part, "")]), patch.object(ov, "_manifest_info", return_value=({}, {})), \
         patch.object(ov, "call_model", side_effect=model):
        ai_review.run({"nodes": []})
    assert seen["logs"][b.ALARM_PART] == lines
