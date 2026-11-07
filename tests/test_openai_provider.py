# File: tests/test_openai_provider.py
# Purpose: REQ-GHA-024 (amended 2026-11-08) — the AI runs on OpenAI; the daily cap and spend
# survive a restart; overviews use the small model, the log review and investigations the larger one

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.analysis import vertex_overview as ov


def _answer(text='{"score": 8, "summary": "ok", "issues": [], "recommendations": []}',
            usage=(300, 150), extra=()):
    out = list(extra) + [{"type": "message", "content": [{"type": "output_text", "text": text, "annotations": [
        {"type": "url_citation", "url": "https://status.example.com/x", "title": "Status"}]}]}]
    return SimpleNamespace(status_code=200, json=lambda: {"output": out, "usage": {"input_tokens": usage[0], "output_tokens": usage[1]}})


@pytest.fixture
def openai(tmp_path, monkeypatch):
    monkeypatch.setattr(ov, "PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AI_STATE_DIR", str(tmp_path))
    with ov._lock:
        ov._spend.clear(); ov._spend.update(ov._new_day())
    ov.refresh_durable_spend()
    return tmp_path


def test_an_overview_uses_the_small_model_with_a_json_answer(openai):
    with patch("httpx.post", return_value=_answer()) as post:
        text, _ = ov.call_model("Write JSON.", '{"part": "x"}')
    body = post.call_args.kwargs["json"]
    assert body["model"] == ov.OPENAI_MODEL == "gpt-5.4-nano"
    assert body["text"]["format"]["type"] == "json_object" and "json" in body["input"].lower()
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer test-key"
    assert json.loads(text)["summary"] == "ok"


def test_the_log_review_and_investigations_use_the_larger_model_with_search(openai):
    search = {"type": "web_search_call", "action": {"query": "cloudflare status"}}
    with patch("httpx.post", return_value=_answer(extra=[search])) as post:
        _, sources = ov.call_model("Investigate.", "{}", search=True, deep=True)
    body = post.call_args.kwargs["json"]
    assert body["model"] == "gpt-5.4-mini" and body["tools"] == [{"type": "web_search"}]
    assert {"query": "cloudflare status"} in sources
    assert {"title": "Status", "uri": "https://status.example.com/x"} in sources


def test_cost_is_counted_at_each_models_price(openai):
    with patch("httpx.post", return_value=_answer(usage=(1_000_000, 0))):
        ov.call_model("s", "{}")                 # nano: $0.20
        ov.call_model("s", "{}", deep=True)      # mini: $0.75
    sp = ov.get_spend()
    assert sp["calls"] == 2 and sp["cost_usd"] == pytest.approx(0.95)


def test_the_daily_count_survives_a_restart_and_the_cap_still_holds(openai, monkeypatch):
    with patch("httpx.post", return_value=_answer()):
        ov.call_model("s", "{}")
        ov.call_model("s", "{}")
    saved = json.loads((openai / "ai_spend.json").read_text())
    assert saved["calls"] == 2 and saved["day"] == ov._today()
    with ov._lock:   # a restart: memory is empty, the saved count is read back
        ov._spend.clear(); ov._spend.update(ov._new_day())
    ov.refresh_durable_spend()
    assert ov.get_spend()["calls"] == 2
    monkeypatch.setattr(ov, "DAILY_CALL_CAP", 2)
    with pytest.raises(ov.CapReached):
        ov.call_model("s", "{}")


def test_a_refused_call_still_counts_and_says_why(openai):
    with patch("httpx.post", return_value=SimpleNamespace(status_code=429, json=lambda: {})):
        with pytest.raises(RuntimeError, match="OpenAI HTTP 429"):
            ov.call_model("s", "{}")
    assert ov.get_spend()["calls"] == 1


def test_no_key_means_no_call(openai, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY")
    with patch("httpx.post") as post, pytest.raises(RuntimeError, match="not configured"):
        ov.call_model("s", "{}")
    post.assert_not_called()


def test_log_reads_are_paced_and_a_refusal_is_retried(monkeypatch):
    calls, slept = [], []
    answers = [SimpleNamespace(status_code=429, json=lambda: {}),
               SimpleNamespace(status_code=200, json=lambda: {"entries": [{"textPayload": "x"}]})]
    monkeypatch.setattr(ov, "_headers", lambda: {})
    with patch("httpx.post", side_effect=lambda *a, **k: calls.append(1) or answers[len(calls) - 1]):
        entries = ov._read_entries({}, sleep=slept.append)
    assert entries == [{"textPayload": "x"}] and len(calls) == 2 and 5 in slept


def test_log_reads_give_up_after_repeated_refusals(monkeypatch):
    monkeypatch.setattr(ov, "_headers", lambda: {})
    with patch("httpx.post", return_value=SimpleNamespace(status_code=429, json=lambda: {})) as post, \
            pytest.raises(RuntimeError, match="429"):
        ov._read_entries({}, sleep=lambda s: None)
    assert post.call_count == 4
