# File: src/analysis/selection_review.py
# Purpose: REQ-GHA-046: the short AI review of a selection of systems (all, or one group),
#   written from the systems' saved records and rewritten only when one of them changes.

import json
import logging
import os
import re
import tempfile
import threading
import time

logger = logging.getLogger(__name__)

SCOPES = ("all", "group-internal", "group-external")
SETTLE_S = 90       # a round rewrites records one by one: wait until they stop changing
RETRY_S = 600

PROMPT = """You tell a person responsible for several systems how things stand across them, in a few seconds of reading.
You get each system's condition, its latest assessment and its real open alerts.
Write one to three short sentences of plain prose about the selection as a whole: are things generally fine, and what, if anything, deserves a call-out.
Rules:
- Speak about the whole situation. Name a system only to call something out; never go through the systems one by one.
- No lists, no bullet points, no headings. Never enumerate incidents, locations, components, findings or alert numbers.
- Never mention configuration notes, observations, leftovers, cleanup or anything not checked. They are not part of this review.
- A system whose condition is "failing", or "attention" because of a real fault or a provider-reported problem, is called out in a few words.
- If nothing deserves a call-out, say plainly that all is going fine.
- Agree with each system's condition; never contradict it.
Answer in JSON only: {"summary": "the review"}"""

_LIST_LINE = re.compile(r"(?m)^\s*([-*•]|\d+[.)])\s")
_lock = threading.Lock()
_reviews: dict = {}     # scope -> {summary, analyzed_at, sig}
_seen: dict = {}        # scope -> (sig, since when)
_failed_at: dict = {}   # scope -> (sig, when)
_loaded = [False]
_unsaved = [False]      # a written review has not reached storage yet: retried without a new AI call
problem = [None]        # why the reviews could not be read or saved, in words (raises the saving alarm)


def _file():
    d = os.getenv("AI_STATE_DIR", "")
    return os.path.join(d, "ai_selection.json") if d else None


def _load() -> None:
    """A temporary read failure is retried: valid saved reviews are never paid for again."""
    with _lock:
        if _loaded[0]:
            return
        path = _file()
        try:
            if path and os.path.exists(path):
                with open(path) as f:
                    _reviews.update(json.load(f))
            _loaded[0] = True
            problem[0] = None
        except OSError as e:
            problem[0] = f"the saved AI reviews could not be read ({type(e).__name__})"
            logger.warning(problem[0])
        except ValueError as e:      # a damaged file will not heal: the next review replaces it
            _loaded[0] = True
            problem[0] = f"the saved AI reviews could not be read ({type(e).__name__})"
            logger.warning(problem[0])


def _save() -> None:
    path = _file()
    if not path:
        problem[0] = "no folder is set up to keep the AI reviews (AI_STATE_DIR)"
        return
    with _lock:
        text = json.dumps(_reviews)
    try:
        fd, tmp = tempfile.mkstemp(prefix=".ai_selection.", dir=os.path.dirname(path))
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, path)
        _unsaved[0] = False
        problem[0] = None
    except Exception as e:
        problem[0] = f"the AI reviews could not be saved ({type(e).__name__})"
        logger.warning(problem[0])


def _in_scope(scope: str, product: str, outside: set) -> bool:
    if scope == "all":
        return True
    return (product in outside) == (scope == "group-external")


def _signature(records: dict) -> str:
    return "|".join(f"{p}:{r.get('analyzed_at')}:{r.get('condition')}" for p, r in sorted(records.items()))


def _real_alerts(record: dict) -> list:
    """Clause 5: observations and configuration notes are not given to the model at all."""
    return [a.get("title") for a in record.get("alerts") or []
            if a.get("kind") not in ("observation", "example") and a.get("severity") in ("critical", "warning")
            and not str(a.get("rule_id") or "").startswith("finding:")]


def _write(records: dict) -> str:
    from src.analysis import vertex_overview as ov
    payload = ov.sanitize([{"system": p, "condition": r.get("condition"), "assessment": r.get("summary"),
                            "alerts": _real_alerts(r)} for p, r in sorted(records.items())])
    text, _ = ov.call_model(PROMPT, json.dumps(payload, default=str))
    summary = (ov.parse_json(text) or {}).get("summary")
    if not isinstance(summary, str) or not summary.strip() or _LIST_LINE.search(summary):
        raise ValueError("the model's answer was not prose")
    return summary.strip()


def _by_scope() -> dict:
    """scope -> the saved records of that selection that have an evaluation."""
    from src.analysis import vertex_overview as ov
    outside = ov._outside_products()
    cards = {p: r for p, r in ov.system_cards().items() if r.get("summary") and r.get("condition")}
    return {s: {p: r for p, r in cards.items() if _in_scope(s, p, outside)} for s in SCOPES}


def refresh_due(now: float = None) -> None:
    """Clause 11: a selection is rewritten only after one of its records changed and things settled."""
    from src.analysis import vertex_overview as ov
    _load()
    if not _loaded[0]:
        return
    if _unsaved[0]:
        _save()
    if ov.ai_offline():
        return
    now = time.time() if now is None else now
    changed = False
    for scope, records in _by_scope().items():
        if not records:
            continue
        sig = _signature(records)
        with _lock:
            current = (_reviews.get(scope) or {}).get("sig")
        if sig == current:
            continue
        if (_seen.get(scope) or (None,))[0] != sig:
            _seen[scope] = (sig, now)
        failed = _failed_at.get(scope)
        if now - _seen[scope][1] < SETTLE_S or (failed and failed[0] == sig and now - failed[1] < RETRY_S):
            continue
        try:
            summary = _write(records)
        except Exception as e:
            _failed_at[scope] = (sig, now)
            logger.warning(f"selection review {scope} failed: {type(e).__name__}")
            continue
        with _lock:
            _reviews[scope] = {"summary": summary, "analyzed_at": now, "sig": sig}
        changed = True
    if changed:
        _unsaved[0] = True
        _save()


def get_reviews() -> dict:
    """Clause 7: a review written from older records says so; its text and time are kept."""
    _load()
    out = {}
    for scope, records in _by_scope().items():
        with _lock:
            v = dict(_reviews.get(scope) or {})
        if not records and not v:
            continue
        sig = _signature(records)
        out[scope] = {"summary": v.get("summary"), "analyzed_at": v.get("analyzed_at"), "current": v.get("sig") == sig,
                      "update_failed": (_failed_at.get(scope) or (None,))[0] == sig}
    return out
