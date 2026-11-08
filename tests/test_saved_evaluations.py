# File: tests/test_saved_evaluations.py
# Purpose: REQ-GHA-042 — saved evaluations, no new round on restart, alert numbers, AI offline

import json
import time
from unittest.mock import patch

import pytest

from src.analysis import ai_budget as b, vertex_overview as ov
from src.models.alert import Alert, alarm_number

GOOD = {"score": 9, "condition": "normal", "summary": "Fine.", "issues": [], "recommendations": []}
MANIFESTS = [{"product": "sys", "project_id": ""}, {"product": "ext", "kind": "outside_view"}]
TOPOLOGY = {"nodes": [{"id": "a", "label": "A", "project": "sys", "status": "healthy", "metrics": {}}]}


def _forget():
    with ov._lock:
        ov._system = {}
        for d in (ov._own, ov._outside, ov._parts, ov._outside_sig, ov._state_sig, ov._own_jobs, ov._triggered_sig):
            d.clear()
        ov._changed.clear()
    ov._last_round[0] = 0.0
    ov._records_problem[0] = None


@pytest.fixture(autouse=True)
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(ov, "PROVIDER", "openai")
    monkeypatch.setenv("AI_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    _forget()
    b._since_here[0] = None; b._was_blocked.clear()
    with patch("src.api.routes.manifests._load_manifests", return_value=MANIFESTS), \
         patch.object(ov, "_log_lines", return_value=[]), patch("src.rules.engine.get_alerts", return_value=[]):
        yield tmp_path
    _forget()


def test_a_record_survives_a_restart_with_its_original_time():
    with patch.object(ov, "_generate", return_value=GOOD):
        ov.run_own_systems(TOPOLOGY)
    before = ov.system_cards()["sys"]
    _forget()
    ov._load_records()
    after = ov.system_cards()["sys"]
    assert (after["summary"], after["condition"], after["analyzed_at"]) == (before["summary"], before["condition"], before["analyzed_at"])


def test_a_save_that_fails_says_so_and_raises_an_alarm(monkeypatch):
    from src.rules import engine
    with patch("tempfile.mkstemp", side_effect=OSError):
        ov._save_records()
    assert "could not be saved" in ov._records_problem[0]
    with engine._lock:
        engine._active.clear()
    with patch.object(ov.ai_budget, "alarms", return_value=[]), patch.object(ov.ai_budget, "monitor"):
        ov._sync_budget_alarms()
    with engine._lock:
        assert [k for k in engine._active if k[0] == "budget:saving"]
        engine._active.clear()


def test_a_restart_starts_no_new_round_and_waits_until_it_is_due():
    class End(BaseException):
        pass
    now = time.time()
    (ov._records_file() and open(ov._records_file(), "w").write(json.dumps({"last_round": now - 3600, "system": {"summary": "x"}})))
    waited = []

    class Stop:
        def wait(self, s=None):
            waited.append(s)
            raise End
    with patch.object(ov.threading, "Thread"), patch.object(ov.threading, "Event", return_value=Stop()), \
         patch.object(ov, "_fill_missing"), patch.object(ov, "run_all", side_effect=AssertionError("no new round")), \
         pytest.raises(End):
        ov.overview_loop(lambda: TOPOLOGY, ready_fn=lambda: True)
    assert waited and waited[0] == pytest.approx(ov.INTERVAL_S - 3600, abs=5)


def test_only_what_has_no_saved_evaluation_is_evaluated():
    with ov._lock:
        ov._system = {"summary": "x"}
        ov._parts["have"] = {"summary": "s"}
    walked = [({"id": "have"}, ""), ({"id": "new"}, "")]
    with patch.object(ov, "_walk_parts", return_value=walked), patch.object(ov, "run_system") as sys_, \
         patch.object(ov, "_run_part") as part, patch.object(ov, "run_outside") as out, patch.object(ov, "refresh_durable_spend"):
        ov._fill_missing(TOPOLOGY)
    sys_.assert_not_called()
    assert [c.args[0]["id"] for c in part.call_args_list] == ["new"]
    assert out.call_args.kwargs["overviews"] == {"ext"}


def test_an_alarm_keeps_its_number():
    a = Alert(rule_id="r", severity="critical", message="m", triggered_at="t", group="g", node_id="n")
    assert a.to_dict()["number"] == alarm_number("g", "n")
    assert 10000 <= a.to_dict()["number"] <= 99999


def test_ai_offline_only_when_no_provider_can_be_called():
    assert ov.ai_offline() is None
    b.charge("openai", 20)
    assert ov.ai_offline() is None                  # the backup still works
    b.charge("anthropic", 20)
    b.monitor()
    off = ov.ai_offline()
    assert off["alert"] == alarm_number("budget:all", b.ALARM_PART) and off["since"]
    cards = ov.system_cards()
    assert cards["sys"]["ai_offline"] == off and cards["ext"]["ai_offline"] == off


def test_offline_time_survives_a_restart_and_clears(monkeypatch):
    b.charge("openai", 20); b.charge("anthropic", 20)
    b.monitor()
    since = b.offline_since()
    b._since_here[0] = None
    assert b.offline_since() == since
    monkeypatch.setenv("ANTHROPIC_MONTHLY_LIMIT_USD", "50")
    b.monitor()
    assert ov.ai_offline() is None and b.offline_since() is None


def test_an_older_snapshot_cannot_land_after_a_newer_save():
    import threading
    entered, release, order = threading.Event(), threading.Event(), []
    real = ov.json.dumps

    def dumps(obj, **k):
        text = real(obj, **k)
        if isinstance(obj, dict) and "last_round" in obj and not order:
            order.append(1)
            entered.set()
            release.wait(2)
        return text
    with ov._lock:
        ov._own["sys"] = {"summary": "old"}
    with patch.object(ov.json, "dumps", side_effect=dumps):
        first = threading.Thread(target=ov._save_records)
        first.start()
        assert entered.wait(2)
        release.set()
        first.join(2)
        with ov._lock:
            ov._own["sys"] = {"summary": "new"}
        ov._save_records()
    assert json.load(open(ov._records_file()))["own"]["sys"]["summary"] == "new"


def test_a_partial_first_round_counts_from_its_newest_evaluation():
    t = time.time() - 600
    open(ov._records_file(), "w").write(json.dumps({"last_round": 0, "own": {"sys": {"summary": "x", "analyzed_at": t}}}))
    assert ov._load_records() == pytest.approx(t)


def test_nothing_saved_but_errors_means_start_at_once():
    open(ov._records_file(), "w").write(json.dumps({"last_round": 0, "parts": {"p": {"summary": "", "analyzed_at": None, "error": "x"}}}))
    assert ov._load_records() == 0.0


def test_an_error_entry_is_not_an_evaluation():
    with ov._lock:
        ov._system = {"summary": "x"}
        ov._parts["bad"] = {"summary": "", "analyzed_at": None, "error": "x"}
        ov._outside["ext"] = {"summary": "", "error": "x"}
    with patch.object(ov, "_walk_parts", return_value=[({"id": "bad"}, "")]), patch.object(ov, "_run_part") as part, \
         patch.object(ov, "run_outside") as out, patch.object(ov, "refresh_durable_spend"):
        ov._fill_missing(TOPOLOGY)
    assert part.call_count == 1 and out.call_args.kwargs["overviews"] == {"ext"}


def test_the_offline_alert_is_opened_by_identity():
    b.charge("openai", 20); b.charge("anthropic", 20); b.monitor()
    off = ov.ai_offline()
    assert (off["group"], off["node_id"]) == ("budget:all", b.ALARM_PART)


def test_a_finished_analysis_is_saved_before_the_batch_ends(monkeypatch):
    monkeypatch.setattr(ov, "CHECKPOINT_S", 0)
    with patch.object(ov, "_generate", return_value={"score": 8, "summary": "done", "issues": [], "recommendations": []}):
        ov._run_part({"id": "p"}, "", [])
    assert json.load(open(ov._records_file()))["parts"]["p"]["summary"] == "done"


def test_checkpoints_are_spaced_out(monkeypatch):
    monkeypatch.setattr(ov, "CHECKPOINT_S", 3600)
    ov._last_checkpoint[0] = 0.0
    with patch.object(ov, "_save_records") as save, patch.object(ov.time, "monotonic", side_effect=[7200.0, 7201.0]):
        ov._checkpoint(); ov._checkpoint()
    assert save.call_count == 1
