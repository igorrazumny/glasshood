# File: tests/test_assessment_lifecycle.py
# Purpose: REQ-GHA-024 (amended 2026-11-08) — a system's assessment job says truthfully what is
# happening, retries a limited number of times, and never runs twice at once.

import threading
import time
from unittest.mock import patch

import pytest

from src.analysis import vertex_overview as ov

GOOD = {"score": 9, "summary": "Fine.", "issues": [], "recommendations": []}
TOPOLOGY = {"nodes": [{"id": "a", "label": "A", "project": "sys", "status": "healthy", "metrics": {}}]}
MANIFESTS = [{"product": "sys", "project_id": ""}, {"product": "ext", "kind": "outside_view"}]


@pytest.fixture(autouse=True)
def clean():
    with ov._lock:
        ov._own.clear()
        ov._own_jobs.clear()
    with patch("src.api.routes.manifests._load_manifests", return_value=MANIFESTS), \
         patch.object(ov, "_log_lines", return_value=[]):
        yield


def run(side_effect, only_pending=False):
    with patch.object(ov, "_generate", side_effect=side_effect) as gen:
        ov.run_own_systems(TOPOLOGY, only_pending=only_pending)
    return gen


def make_due():
    with ov._lock:
        job = ov._own_jobs.get("sys")
        if job and "retry_at" in job:
            job["retry_at"] = 0


def test_a_system_never_assessed_is_not_said_to_be_running():
    assert ov.get_own("sys") is None
    assert "sys" not in ov.system_cards()


def test_a_finished_assessment_is_not_due_again():
    run([GOOD])
    assert ov.get_own("sys")["job"]["status"] == "complete"
    assert run([GOOD], only_pending=True).call_count == 0


def test_a_passing_failure_retries_a_limited_number_of_times_then_says_failed():
    failure = RuntimeError("OpenAI HTTP 503")
    assert run(failure, only_pending=True).call_count == 1
    assert ov.get_own("sys")["job"]["status"] == "retrying"
    assert run(failure, only_pending=True).call_count == 0     # not before its scheduled time
    make_due()
    run(failure, only_pending=True)
    make_due()
    run(failure, only_pending=True)
    assert ov.get_own("sys")["job"]["status"] == "failed"
    make_due()
    assert run(failure, only_pending=True).call_count == 0     # bounded


@pytest.mark.parametrize("failure", [ov.CapReached("daily cap reached"), RuntimeError("OpenAI key not configured"),
                                     RuntimeError("OpenAI HTTP 401")])
def test_a_failure_that_would_repeat_is_not_retried(failure):
    run(failure, only_pending=True)
    assert ov.get_own("sys")["job"]["status"] == "failed"
    assert run(failure, only_pending=True).call_count == 0


@pytest.mark.parametrize("message", ["OpenAI HTTP 429", "OpenAI HTTP 408", "OpenAI HTTP 500", "connection reset"])
def test_a_passing_failure_is_retried(message):
    assert ov._worth_retrying(RuntimeError(message))


def test_a_failed_refresh_keeps_the_last_good_text_and_its_age():
    run([GOOD])
    written = ov.get_own("sys")["analyzed_at"]
    run(RuntimeError("OpenAI HTTP 503"))
    entry = ov.get_own("sys")
    assert (entry["summary"], entry["analyzed_at"]) == ("Fine.", written)
    assert entry["error"] and entry["job"]["status"] == "retrying"


def test_two_runs_of_one_system_never_compete():
    started, release = threading.Event(), threading.Event()
    calls = []

    def slow(*_):
        calls.append(1)
        started.set()
        release.wait(5)
        return GOOD
    with patch.object(ov, "_generate", side_effect=slow):
        first = threading.Thread(target=ov.run_own_systems, args=(TOPOLOGY,))
        first.start()
        assert started.wait(5)
        assert ov.get_own("sys")["job"]["status"] == "running"
        ov.run_own_systems(TOPOLOGY)                      # a manual refresh during the run
        release.set()
        first.join(5)
    assert len(calls) == 1


def test_the_scan_assesses_a_new_system_and_reads_nothing_when_none_is_due():
    topology = lambda: TOPOLOGY                           # noqa: E731
    with patch.object(ov, "refresh_durable_spend"), patch.object(ov, "_generate", return_value=GOOD) as gen:
        ov._pending_scan_once(topology)
        assert gen.call_count == 1
        unread = patch.object(ov, "refresh_durable_spend", side_effect=AssertionError("nothing is due"))
        with unread:
            ov._pending_scan_once(lambda: pytest.fail("the topology must not be built"))
    assert ov.get_own("sys")["summary"] == "Fine."


def test_the_scan_does_not_wait_for_a_long_round():
    started, finish = threading.Event(), threading.Event()
    scans = []

    def long_round(_):
        started.set()
        finish.wait(5)

    def scan(_):
        scans.append(1)
        finish.set()
    with patch.object(ov, "run_all", side_effect=long_round), patch.object(ov, "_pending_scan_once", side_effect=scan), \
         patch.object(ov, "PENDING_SCAN_S", 0.01), patch("src.analysis.ai_review.run"), patch.object(ov, "INTERVAL_S", 3600):
        threading.Thread(target=ov.overview_loop, args=(lambda: TOPOLOGY,), daemon=True).start()
        assert started.wait(5)
        deadline = time.monotonic() + 5
        while not scans and time.monotonic() < deadline:
            time.sleep(0.01)
    assert scans
