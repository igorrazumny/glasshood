# File: tests/test_coldvault_models.py
# Purpose: REQ-GHA-034 — a failing AI model, and the backup that answered for it, is visible

import json

from src.collectors import coldvault_models as cm
from src.rules import engine

READ = {"read": True, "reason": ""}

OPUS_ERROR = {"timestamp": "2026-11-07T20:26:11.880Z", "severity": "ERROR", "request_id": "r1",
              "logger": "src.llm.providers.claude_streaming",
              "message": "Claude stream failed: Claude Opus 4.7 - RateLimitError: Error code: 429 - Quota exceeded"}
OPUS_FALLBACK = {"timestamp": "2026-11-07T20:26:11.881Z", "severity": "INFO", "request_id": "r1",
                 "message": "Fallback: Claude Opus 4.7 failed (Error code: 429 - quota), trying Claude Sonnet 4.6"}
SONNET_BILLING = {"timestamp": "2026-11-07T20:26:15Z", "severity": "INFO", "request_id": "r1",
                  "message": "billing", "event": "billing", "model": "Claude Sonnet 4.6"}


def _lines(*items):
    return [{**i, "_raw": json.dumps(i)} for i in items]


def _reader(failure_lines, billing_lines):
    def read(project, log_filter, max_entries=200):
        return _lines(*billing_lines) if "billing" in log_filter else _lines(*failure_lines)
    return read


def _metrics(per_model):
    return {"requests": {"per_model": per_model}}


def _setup(monkeypatch, per_model, failure_lines=(), billing_lines=()):
    monkeypatch.setattr(cm, "_source", lambda: {"project": "p", "filter": "app"})
    cm.refresh(_metrics(per_model), READ, read_lines=_reader(failure_lines, billing_lines))


def test_backup_answered_gives_a_warning_naming_both_models_and_the_reason(monkeypatch):
    _setup(monkeypatch, {"claude-opus-4-7": {"answered": 0, "failed": 1, "timed_out": 0},
                         "claude-sonnet-4-6": {"answered": 2, "failed": 0, "timed_out": 0}},
           [OPUS_FALLBACK, OPUS_ERROR], [SONNET_BILLING])
    [f] = cm.failures({"claude": "cv-vertex"})
    assert f["part"] == "cv-vertex" and f["severity"] == "warning" and f["model"] == "claude-opus-4-7"
    assert "Claude Opus 4.7" in f["title"] and "Claude Sonnet 4.6 answered instead" in f["title"]
    assert "429" in f["explanation"]["what"] and "Claude Sonnet 4.6" in f["explanation"]["what"]
    assert "likely" in f["explanation"]["suspicion"]
    assert len(f["evidence"]) == 2
    b = cm.box(["claude", "gemini"])
    assert b["status"] == "degraded"
    assert "Claude Opus 4.7 failed 1 time" in b["check_description"]
    assert {m["id"] for m in b["metrics"]["models"]} == {"claude-opus-4-7", "claude-sonnet-4-6"}


def test_no_other_model_answered_gives_a_critical_alarm(monkeypatch):
    _setup(monkeypatch, {"claude-opus-4-7": {"answered": 0, "failed": 2, "timed_out": 0}}, [OPUS_ERROR], [])
    [f] = cm.failures({"claude": "cv-vertex"})
    assert f["severity"] == "critical" and "1 question got no reply" in f["title"]
    assert "got no answer" in f["explanation"]["what"]
    assert cm.box(["claude"])["status"] == "error"


def test_backup_counted_only_when_it_answered(monkeypatch):
    _setup(monkeypatch, {"claude-opus-4-7": {"answered": 0, "failed": 1, "timed_out": 0},
                         "claude-sonnet-4-6": {"answered": 0, "failed": 1, "timed_out": 0}},
           [OPUS_FALLBACK, OPUS_ERROR], [])
    sev = {f["model"]: f["severity"] for f in cm.failures({"claude": "cv-vertex"})}
    assert sev["claude-opus-4-7"] == "critical"


def test_model_with_no_calls_is_idle_not_failing(monkeypatch):
    _setup(monkeypatch, {"claude-opus-4-7": {"answered": 3, "failed": 0, "timed_out": 0}})
    assert cm.box(["openai"])["status"] == "idle"
    assert cm.box(["claude"])["status"] == "healthy"
    assert cm.failures({"claude": "cv-vertex"}) == []


def test_no_per_model_figures_never_shows_healthy():
    cm.refresh({"requests": {}}, READ)
    b = cm.box(["claude"])
    assert b["status"] == "not checked" and "does not report per-model figures" in b["check_description"]
    cm.refresh({}, {"read": False, "reason": "ColdVault refused the request (HTTP 401)"})
    assert "HTTP 401" in cm.box(["claude"])["check_description"]


def test_model_ids_and_names_match():
    assert cm._id_for("Claude Opus 4.7", ["claude-opus-4-7"]) == "claude-opus-4-7"
    assert cm._id_for("GPT-5.4", ["gpt-5.4"]) == "gpt-5.4"
    assert cm._id_for("GLM-5.3 Flash", ["redpill/glm-5.3-flash"]) == "redpill/glm-5.3-flash"
    assert cm.provider_of("claude-opus-4-7") == "claude" and cm.provider_of("xai/grok-4") == "grok"


def test_reasons_in_plain_words():
    assert "usage limit" in cm.plain_reason("RateLimitError: Error code: 429")
    assert "timeout" in cm.plain_reason("ReadTimeout")
    assert cm.plain_reason("") == "no reason given"


OPUS_ERROR_R2 = {**OPUS_ERROR, "request_id": "r2", "timestamp": "2026-11-07T20:30:00Z"}
SONNET_UNRELATED = {**SONNET_BILLING, "request_id": "unrelated-r9"}
TWO_FAILED = {"claude-opus-4-7": {"answered": 0, "failed": 2, "timed_out": 0},
              "claude-sonnet-4-6": {"answered": 1, "failed": 0, "timed_out": 0}}


def test_an_unrelated_success_is_not_taken_as_recovery(monkeypatch):
    # shadow C1: Sonnet answered another question, not the one Opus failed
    _setup(monkeypatch, {"claude-opus-4-7": {"answered": 0, "failed": 1, "timed_out": 0},
                         "claude-sonnet-4-6": {"answered": 1, "failed": 0, "timed_out": 0}},
           [OPUS_FALLBACK, OPUS_ERROR], [SONNET_UNRELATED])
    [f] = cm.failures({"claude": "cv-vertex"})
    assert f["severity"] == "critical" and "answered instead" not in f["title"]


def test_partial_recovery_keeps_the_unanswered_question_critical(monkeypatch):
    _setup(monkeypatch, TWO_FAILED, [OPUS_ERROR_R2, OPUS_FALLBACK, OPUS_ERROR], [SONNET_BILLING])
    [f] = cm.failures({"claude": "cv-vertex"})
    assert f["severity"] == "critical"
    assert "Claude Sonnet 4.6 answered 1 question" in f["explanation"]["what"]
    assert "1 question got no reply" in f["explanation"]["what"]


def test_unreadable_lines_never_claim_no_reply(monkeypatch):
    # shadow C2: a log read failure is not evidence that nobody answered
    monkeypatch.setattr(cm, "_source", lambda: {"project": "p", "filter": "app"})
    with cm._lock:
        cm._state["models"] = {}

    def broken(*a, **k):
        raise PermissionError("denied")
    cm.refresh(_metrics({"claude-opus-4-7": {"answered": 0, "failed": 1, "timed_out": 0},
                         "claude-sonnet-4-6": {"answered": 1, "failed": 0, "timed_out": 0}}), READ, read_lines=broken)
    [f] = cm.failures({"claude": "cv-vertex"})
    assert f["severity"] == "warning" and "not known" in f["title"]
    assert "PermissionError" in f["explanation"]["what"]
    assert cm.box(["claude"])["status"] == "degraded"


def test_a_confirmed_recovery_survives_a_later_unreadable_reading(monkeypatch):
    per_model = {"claude-opus-4-7": {"answered": 0, "failed": 1, "timed_out": 0},
                 "claude-sonnet-4-6": {"answered": 2, "failed": 0, "timed_out": 0}}
    _setup(monkeypatch, per_model, [OPUS_FALLBACK, OPUS_ERROR], [SONNET_BILLING])

    def broken(*a, **k):
        raise TimeoutError()
    cm.refresh(_metrics(per_model), READ, read_lines=broken)
    [f] = cm.failures({"claude": "cv-vertex"})
    assert f["severity"] == "warning" and "Claude Sonnet 4.6 answered instead" in f["title"]


def test_failures_without_request_ids_are_unknown(monkeypatch):
    no_id = {k: v for k, v in OPUS_ERROR.items() if k != "request_id"}
    _setup(monkeypatch, {"claude-opus-4-7": {"answered": 0, "failed": 1, "timed_out": 0}}, [no_id], [])
    [f] = cm.failures({"claude": "cv-vertex"})
    assert f["severity"] == "warning" and "not known" in f["title"]


def test_one_event_raises_one_alarm_not_two(monkeypatch):
    # shadow C3: the provider box's error comes from the model failure; node_error adds no second alarm
    from src.models.topology import Node
    _reset_engine()
    _setup(monkeypatch, {"claude-opus-4-7": {"answered": 0, "failed": 1, "timed_out": 0}}, [OPUS_ERROR], [])
    engine.track_model_failures(cm.failures({"claude": "cv-vertex"}), True)
    node = Node(id="cv-vertex", label="Vertex AI", type="provider", status=cm.box(["claude"])["status"])
    rule = {"id": "node_error", "group": "status", "severity": "critical", "scope": "node",
            "condition": {"metric": "status", "operator": "==", "value": "error"}}
    monkeypatch.setattr(engine, "_rules", lambda path: [rule])
    engine.evaluate_rules([node], {})
    on_box = [a for a in engine.get_alerts() if a["node_id"] == "cv-vertex"]
    assert [a["group"] for a in on_box] == ["model:claude-opus-4-7"]
    _reset_engine()


def _reset_engine():
    engine._active.clear()
    engine._resolved.clear()


def test_alarm_starts_and_clears_after_the_failures_leave_the_hour(monkeypatch):
    _reset_engine()
    _setup(monkeypatch, {"claude-opus-4-7": {"answered": 0, "failed": 1, "timed_out": 0},
                         "claude-sonnet-4-6": {"answered": 2, "failed": 0, "timed_out": 0}},
           [OPUS_FALLBACK, OPUS_ERROR], [SONNET_BILLING])
    engine.track_model_failures(cm.failures({"claude": "cv-vertex"}), True, {"cv-vertex": "Vertex AI (Partner)"})
    [a] = [a for a in engine.get_alerts() if a["group"] == "model:claude-opus-4-7"]
    assert a["severity"] == "warning" and a["node_id"] == "cv-vertex"
    assert a["title"].startswith("Vertex AI (Partner): Claude Opus 4.7 is failing")
    assert a["explanation"]["what"] and a["evidence"]
    # figures not read: nothing changes
    engine.track_model_failures([], False)
    assert any(a["group"] == "model:claude-opus-4-7" for a in engine.get_alerts())
    # read again with no failures in the hour: the alarm ends
    _setup(monkeypatch, {"claude-opus-4-7": {"answered": 1, "failed": 0, "timed_out": 0}})
    engine.track_model_failures(cm.failures({"claude": "cv-vertex"}), True)
    assert not any(a["group"] == "model:claude-opus-4-7" for a in engine.get_alerts())
    assert any(a["group"] == "model:claude-opus-4-7" for a in engine.get_resolved())
    _reset_engine()
