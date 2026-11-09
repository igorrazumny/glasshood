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
# The contract and instructions a review was written under. Bumped with every revision of the contract or
# of PROMPT, so a saved review of an older version is set aside at load and written once more (one call per
# selection): the owner's live reading (clause 12) is then of the revised instructions, not of a cached text.
SHAPE = 6
SETTLE_S = 90       # a round rewrites records one by one: wait until they stop changing
RETRY_S = 600

PROMPT = """You review the state of a selection of systems for the person responsible for all of them. Each system is one component of the selection.
For each system you get its name, condition, score, latest assessment, the items its own review listed under needs attention, and its real open alerts.
Write in the measured, factual register of an operations report. No conversational openers, no filler, no reassurance beyond the facts.
Rules:
- Use each system's name exactly as given.
- The summary is one or two sentences on the selection as a whole: first the overall situation, then what deserves a call-out. Do not go through the systems one by one. When more than two systems are operating normally, say so collectively ("the other systems are operating normally") rather than naming each.
- Under issues, list only actual faults and provider-reported problems, one plain sentence each, naming the system and saying what is wrong. Never list a system without saying what is wrong with it.
- Configuration notes, observations, leftovers, findings, follow-up items, cleanup and parts that are not checked are outside this review: never mention them, in any words. A system whose attention comes only from such notes gets no issue and no next step; if the summary names it at all, it says only that the system has no operational fault, and never explains or hints why it is marked for attention.
- Never enumerate incidents, locations, components or alert numbers. Describe the pattern and what it means for the business. An external service's trouble is one issue in one sentence: the pattern, never one item per component, location, incident or maintenance.
- Next steps address only the listed issues, at most three, each a concrete action the person responsible for this selection can take. For a problem at an external provider that person is the provider's customer: the steps are to follow the provider's updates, check the selection's own services that depend on it, and prepare or use alternatives. Never tell them to repair the provider's service. No next step for a system operating normally. Empty when issues are empty.
- Agree with each system's condition: a "normal" system is given no problem.
Answer in JSON only:
{"score": 1-10 for the selection as a whole,
 "summary": "one or two sentences",
 "issues": ["one sentence per actual fault or provider-reported problem"],
 "recommendations": ["at most three concrete actions, only for the listed issues"]}"""

# clause 5: words that mean the model carried notes into the review; such an answer is refused
# the phrases a note summary is made of; a fault may still speak of a configuration, a duplicate or a follow-up
_NOTE_WORDS = re.compile(r"(?i)\b(observations?|configuration notes?|configuration (and|or) security\b[^.]*?\bitems?|"
                         r"follow-?up items?|leftovers?|findings?|cleanup (is |remains |items?|notes?)|housekeeping (items?|notes?)|"
                         r"not checked|unverified)\b")
# an issue that names no fault is not an issue (clause 5)
_NON_ISSUE = re.compile(r"(?i)(no operational fault|needs attention\.?$|attention flag)")
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
                    saved = json.load(f)
                kept = {k: v for k, v in saved.items() if isinstance(v, dict) and v.get("shape") == SHAPE}
                if len(kept) != len(saved):
                    # an older contract's text may carry what the amendment forbids: written again once
                    logger.info(f"{len(saved) - len(kept)} saved reviews of an older shape set aside; rewritten at the next scan")
                    _unsaved[0] = True
                _reviews.update(kept)
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


def _prose(value, what: str) -> str:
    if not isinstance(value, str) or not value.strip() or _LIST_LINE.search(value):
        raise ValueError(f"the model's {what} was not prose")
    if _NOTE_WORDS.search(value):
        raise ValueError(f"the model's {what} carried configuration notes into the review")
    return value.strip()


def _names() -> dict:
    """product -> the name the reader sees on the card"""
    from src.api.routes.manifests import _load_manifests
    return {m.get("product"): m.get("solution") or m.get("display_name") or m.get("product") for m in _load_manifests()}


def _as_named(text: str, names: dict) -> str:
    """A system is called by its name as the reader sees it, whatever case the inputs used."""
    for product, name in names.items():
        for word in {product, name}:
            if len(word) < 4:   # a short id could be an ordinary word; only real names are normalised
                continue
            # a dot counts as part of a domain only when a word follows it; a full stop does not
            text = re.sub(rf"(?i)(?<![\w.-]){re.escape(word)}(?![\w-])(?!\.\w)", name, text)
    return text


def _write(records: dict) -> dict:
    """Clauses 2 to 7: the single-system shape, on the stronger model (clause 12)."""
    from src.analysis import vertex_overview as ov
    names = {p: n for p, n in _names().items() if p in records}
    outside = ov._outside_products()
    # an external service's own items and alert titles enumerate its components and incidents (clause 5):
    # the model gets only its condition, score and assessment
    payload = ov.sanitize([{"system": names.get(p) or p, "condition": r.get("condition"), "score": r.get("score"),
                            "assessment": r.get("summary"),
                            **({} if p in outside else {"needs_attention": r.get("issues") or [], "alerts": _real_alerts(r)})}
                           for p, r in sorted(records.items())])
    text, _ = ov.call_model(PROMPT, json.dumps(payload, default=str), deep=True)
    answer = ov.parse_json(text) or {}
    issues, steps = answer.get("issues") or [], answer.get("recommendations") or []
    if not isinstance(issues, list) or not isinstance(steps, list):
        raise ValueError("the model's lists were not lists")
    score = answer.get("score")
    # clause 7: a score is part of the review; clause 6: next steps only where something needs attention
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not 1 <= score <= 10 or score != int(score):
        raise ValueError("the model's score was missing or not a whole number from 1 to 10")
    mentions = lambda text, name: re.search(rf"(?i)\b{re.escape(name)}\b", text) is not None
    issues = [_prose(x, "issue") for x in issues]
    # a true sentence in the wrong place ("ColdVault has no operational fault") is left out, not
    # refused: the rest of the answer stands, and a next step for a system whose item was left out
    # goes with it (clause 6: next steps only for the listed issues)
    dropped = [x for x in issues if _NON_ISSUE.search(x)]
    issues = [x for x in issues if x not in dropped]
    if dropped:
        gone = [n for n in names.values() if any(mentions(x, n) for x in dropped)]
        steps = [s for s in steps if isinstance(s, str) and not any(mentions(s, n) for n in gone)]
    if steps and not issues:
        if dropped:
            steps = []
        else:
            raise ValueError("the model gave next steps although nothing needs attention")
    # one issue per external service in the selection; an internal system's fault that mentions the
    # provider it depends on is that system's issue, not the provider's
    internal = [names.get(p) or p for p in records if p not in outside]
    for p in [p for p in records if p in outside]:
        name = names.get(p) or p
        own = [x for x in issues if mentions(x, name) and not any(mentions(x, n) for n in internal)]
        if len(own) > 1:
            raise ValueError(f"the model split {name}'s trouble into several issues")
    named = lambda s: _as_named(s, names)
    return {"summary": named(_prose(answer.get("summary"), "summary")), "score": int(score),
            "issues": [named(x) for x in issues],
            "recommendations": [named(_prose(x, "next step")) for x in steps[:3]], "shape": SHAPE}


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
            written = _write(records)
        except Exception as e:
            _failed_at[scope] = (sig, now)
            logger.warning(f"selection review {scope} failed: {type(e).__name__}: {str(e)[:200]}")
            continue
        with _lock:
            _reviews[scope] = {**written, "analyzed_at": now, "sig": sig}
        _failed_at.pop(scope, None)   # a success supersedes an earlier failed attempt
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
        out[scope] = {"summary": v.get("summary"), "score": v.get("score"), "issues": v.get("issues") or [],
                      "recommendations": v.get("recommendations") or [],
                      "analyzed_at": v.get("analyzed_at"), "current": v.get("sig") == sig,
                      "update_failed": (_failed_at.get(scope) or (None,))[0] == sig}
    return out
