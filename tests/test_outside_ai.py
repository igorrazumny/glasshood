# File: tests/test_outside_ai.py
# Purpose: REQ-GHA-036 clause 7 — external systems get AI overviews; a part's analysis is
# rewritten only when what the provider publishes about it changed

import json
from unittest.mock import patch

from src.analysis import vertex_overview as ov


def _published(status="operational", updated="2026-11-07T20:00:00Z", incident=None):
    comps = [{"id": "c1", "name": "Amsterdam", "status": status, "updated_at": updated, "group_id": "g"},
             {"id": "c2", "name": "Frankfurt", "status": "operational", "updated_at": updated, "group_id": "g"},
             {"id": "g", "name": "Europe", "group": True}]
    events = [incident] if incident else []
    return [{"name": "Example", "product": "example", "read": True, "error": None, "page": "https://status.example.com",
             "comps": {"c1": "ex-ams", "c2": "ex-fra"}, "components": comps, "events": events}]


def _reset():
    with ov._lock:
        ov._outside.clear(); ov._outside_sig.clear()
        for k in [k for k in ov._parts if k.startswith("ex-")]:
            del ov._parts[k]


def _run(published, calls):
    def gen(prompt, text):
        calls.append((prompt, json.loads(text)))
        return {"score": 8, "summary": "ok", "issues": [], "recommendations": []}
    with patch("src.collectors.statuspage.published", return_value=published), \
         patch.object(ov, "_generate", side_effect=gen):
        return ov.run_outside()


def test_each_external_system_gets_an_overview_and_each_part_an_analysis():
    _reset()
    calls = []
    written = _run(_published(), calls)
    assert written == 2
    assert ov.get_outside("example")["summary"] == "ok"
    assert ov.get_part("ex-ams")["summary"] == "ok"
    system_payload = [p for prompt, p in calls if prompt == ov.OUTSIDE_SYSTEM_PROMPT][0]
    assert system_payload["components_by_state"] == {"operational": 2}


def test_an_unchanged_part_is_not_rewritten():
    _reset()
    _run(_published(), [])
    calls = []
    assert _run(_published(), calls) == 0
    assert [p for p, _ in calls] == [ov.OUTSIDE_SYSTEM_PROMPT]   # only the system overview


def test_a_changed_part_is_rewritten_with_the_providers_words():
    _reset()
    _run(_published(), [])
    incident = {"id": "i1", "name": "Amsterdam degraded", "_kind": "incident", "status": "investigating",
                "impact": "minor", "components": [{"id": "c1", "name": "Amsterdam"}, {"id": "c2", "name": "Frankfurt"}],
                "incident_updates": [{"created_at": "2026-11-07T22:00:00Z", "status": "investigating",
                                      "body": "We are looking into packet loss."}]}
    calls = []
    written = _run(_published(status="degraded_performance", updated="2026-11-07T22:00:00Z", incident=incident), calls)
    assert written == 2   # Amsterdam changed state; Frankfurt is newly named by the incident
    part = [p for prompt, p in calls if prompt == ov.OUTSIDE_PART_PROMPT and p["component"] == "Amsterdam"][0]
    [inc] = part["open_incidents_and_maintenance"]
    assert inc["updates"][0]["text"] == "We are looking into packet loss."
    assert inc["also_affects"] == ["Frankfurt"]
    assert part["group"] == "Europe"


def test_an_unreadable_provider_keeps_the_last_overview_and_says_why():
    _reset()
    _run(_published(), [])
    down = [{"name": "Example", "product": "example", "read": False, "error": "the provider's status could not be read (TimeoutError)",
             "page": "", "comps": {}, "components": [], "events": []}]
    _run(down, [])
    o = ov.get_outside("example")
    assert o["summary"] == "ok" and "could not be read" in o["error"]


def test_prompts_forbid_invented_causes():
    for prompt in (ov.OUTSIDE_SYSTEM_PROMPT, ov.OUTSIDE_PART_PROMPT):
        assert "Never invent an internal cause" in prompt and "cannot be known from outside" in prompt
