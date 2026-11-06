# File: src/analysis/ai_investigate.py
# Purpose: REQ-GHA-029 clauses 3-6 — "Investigate deeper": on request, one investigation of one
# alarm. It reads further back in the part's logs and in its connected parts' logs, may search
# the web for the error, and writes a report that opens with an executive summary. The report
# is saved with the alarm; a later follow-up adds what happened since. Nothing is prepared in
# advance. The model's text is plain data. Investigations and follow-ups have a daily cap on
# top of the overview's daily call cap.

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone

from src.analysis import ai_review
from src.analysis import vertex_overview as ov
from src.rules import engine

logger = logging.getLogger(__name__)

DAILY_CAP = int(os.getenv("INVESTIGATION_DAILY_CAP", "30"))
LOOKBACK_S = 24 * 3600
PART_WARN_LINES, PART_SAMPLE_LINES = 150, 20
RELATED_PARTS, RELATED_WARN_LINES = 4, 30
FOLLOWUP_MAX_S = 7 * 24 * 3600
_lock = threading.Lock()
_count = {"day": "", "n": 0}

REPORT_PROMPT = """You investigate ONE problem in a running cloud system and write a report for a business reader.
You get the alarm, the part's log lines from the last 24 hours (warnings and errors first) and the
log lines of the parts connected to it. You may search the web for the exact error to see whether it
is a known, common problem; say so only if a source supports it.
Work out what happened, in what order, whether it is still going on, happened once, or comes back.
Copy evidence lines exactly as given. Refer to parts by their label. Times as given in the lines.
Answer in JSON only:
{"executive_summary": "three or four plain sentences: what, impact, ongoing or not, what to do",
 "findings": [{"what": "...", "evidence": ["<log line>", ...]}],
 "what_is_happening": "plain explanation",
 "timeline": [{"time": "...", "event": "..."}],
 "pattern": "ongoing" | "once" | "recurring" | "unclear",
 "pattern_explained": "one sentence",
 "known_issue": "what the web says about this error, or empty",
 "conclusion": "...", "next_step": "one concrete suggested next step"}"""

FOLLOWUP_PROMPT = """You follow up on an earlier investigation of ONE problem in a running cloud system.
You get the earlier report's summary and evidence, and the part's log lines written since then.
Say plainly whether the problem happened again, how often, and whether anything changed, for example
"This happened once and has not happened again." Do not invent anything the lines do not show.
Answer in JSON only: {"summary": "one to three plain sentences", "happened_again": true | false}"""


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _take_slot():
    """Count one investigation or follow-up against today's cap; None when taken."""
    with _lock:
        if _count["day"] != _today():
            _count.update(day=_today(), n=0)
        if _count["n"] >= DAILY_CAP:
            return f"daily cap of {DAILY_CAP} investigations reached"
        _count["n"] += 1
        return None


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def _part_filters(topology: dict) -> tuple[dict, dict]:
    filters, labels = {}, {}
    for rec, flt in ov._walk_parts(topology):
        labels[rec["id"]] = rec["label"]
        if flt:
            filters[rec["id"]] = flt
    return filters, labels


def _related(part: str, topology: dict, filters: dict) -> list:
    edges = topology.get("edges") or []
    near = [e.get("target") for e in edges if e.get("source") == part] + \
           [e.get("source") for e in edges if e.get("target") == part]
    out = []
    for p in near:
        if p and p != part and p in filters and p not in out:
            out.append(p)
    return out[:RELATED_PARTS]


def _strs(items, n, size=400) -> list:
    return [str(i)[:size] for i in (items or []) if isinstance(i, (str, int, float))][:n]


def report_from(answer, sources: list, searched: bool, shown: set) -> dict:
    """The report in its fixed order (clause 4); a missing executive summary is a failure.
    Evidence is only a log line the model was shown; a finding left with none is marked
    as not backed by the logs rather than published with an invented quote."""
    if not isinstance(answer, dict) or not str(answer.get("executive_summary") or "").strip():
        raise ValueError("the model's answer had no executive summary")
    findings, dropped = [], 0
    for f in answer.get("findings") or []:
        if isinstance(f, dict) and str(f.get("what") or "").strip():
            quoted = [e for e in (f.get("evidence") or []) if isinstance(e, str)]
            evidence = [e for e in quoted if e in shown][:6]
            dropped += len([e for e in quoted if e not in shown])
            findings.append({"what": str(f["what"])[:600], "evidence": evidence, "backed_by_logs": bool(evidence)})
    timeline = [{"time": str(t.get("time", ""))[:40], "event": str(t.get("event", ""))[:300]}
                for t in (answer.get("timeline") or []) if isinstance(t, dict) and t.get("event")][:20]
    pattern = answer.get("pattern") if answer.get("pattern") in ("ongoing", "once", "recurring") else "unclear"
    text = lambda k, n=1200: str(answer.get(k) or "")[:n]  # noqa: E731
    return {"executive_summary": text("executive_summary"), "findings": findings[:8],
            "what_is_happening": text("what_is_happening", 2000), "timeline": timeline,
            "pattern": pattern, "pattern_explained": text("pattern_explained", 400),
            "known_issue": text("known_issue", 800), "conclusion": text("conclusion"),
            "next_step": text("next_step", 600), "sources": sources, "searched_web": searched,
            "quotes_not_in_logs_dropped": dropped}


def _ask(prompt: str, payload: dict, max_tokens: int, search: bool):
    """payload is already sanitised (the lines checked as evidence are the lines sent)."""
    text_in = json.dumps(payload, default=str)
    if search:
        try:
            text, sources = ov.call_model(prompt, text_in, max_tokens=max_tokens, search=True)
            return ov.parse_json(text), sources, bool(sources)  # searched only if it did
        except ov.CapReached:
            raise
        except Exception as e:  # a model or region without web search: investigate without it
            logger.info(f"investigation without web search ({type(e).__name__})")
    text, _ = ov.call_model(prompt, text_in, max_tokens=max_tokens)
    return ov.parse_json(text), [], False


def _investigate(alarm: dict, user: str, topology: dict) -> None:
    group, part = alarm["group"], alarm["node_id"]
    started = time.time()
    try:
        ov.refresh_durable_spend()
        filters, labels = _part_filters(topology)
        own = ov._log_lines(filters.get(part, ""), PART_WARN_LINES, PART_SAMPLE_LINES, since_s=LOOKBACK_S) \
            if part in filters else []
        related = {labels.get(p, p): ov._log_lines(filters[p], RELATED_WARN_LINES, 0, since_s=LOOKBACK_S)
                   for p in _related(part, topology, filters)}
        payload = {"alarm": {"title": alarm.get("title"), "part": labels.get(part, part),
                             "severity": alarm.get("severity"), "first_seen": alarm.get("first_seen"),
                             "last_seen": alarm.get("last_seen"),
                             "evidence": alarm.get("evidence") or alarm.get("reasons") or []},
                   "part_logs_24h": own, "connected_parts_logs_24h": related}
        payload = ov.sanitize(payload)
        shown = set(payload["part_logs_24h"]) | {l for ls in payload["connected_parts_logs_24h"].values() for l in ls}
        answer, sources, searched = _ask(REPORT_PROMPT, payload, 4000, search=True)
        report = report_from(answer, sources, searched, shown)
        report.update(status="done", requested_by=user, started_at=_iso(started),
                      written_at=_iso(time.time()), lines_read=len(own) + sum(map(len, related.values())),
                      followups=[])
    except Exception as e:
        why = str(e) if isinstance(e, ov.CapReached) else f"{type(e).__name__}: {str(e)[:160]}"
        logger.warning(f"investigation of {group}/{part} failed: {why}")
        report = {"status": "failed", "error": why, "requested_by": user, "started_at": _iso(started)}
    engine.set_report(group, part, report)
    ai_review.save()


def start(group: str, part, user: str, topology: dict, run_async: bool = True):
    """Start one investigation of one alarm. Returns None when started, else why not."""
    alarm = engine.find_alarm(group, part)
    if alarm is None:
        return "alarm not found"
    if (alarm.get("report") or {}).get("status") == "running":
        return "an investigation of this alarm is already running"
    refused = _take_slot()
    if refused:
        return refused
    engine.set_report(group, part, {"status": "running", "requested_by": user,
                                    "started_at": _iso(time.time())})
    if run_async:
        threading.Thread(target=_investigate, args=(alarm, user, topology), daemon=True,
                         name="investigate").start()
    else:
        _investigate(alarm, user, topology)
    return None


def followup(group: str, part, user: str, topology: dict):
    """Clause 5: add what happened since the report. Returns (followup entry, error)."""
    alarm = engine.find_alarm(group, part)
    report = (alarm or {}).get("report") or {}
    if report.get("status") != "done":
        return None, "there is no finished report to follow up"
    filters, _ = _part_filters(topology)
    if part not in filters:
        return None, "this part has no log location in its landscape file"
    refused = _take_slot()
    if refused:
        return None, refused
    try:
        last = (report.get("followups") or [{}])[-1].get("at") or report["written_at"]
        since_s = min(FOLLOWUP_MAX_S, max(60, int(time.time() - datetime.fromisoformat(last).timestamp())))
        ov.refresh_durable_spend()
        lines = ov._log_lines(filters[part], PART_WARN_LINES, 0, since_s=since_s)
        payload = {"earlier_report": {"executive_summary": report.get("executive_summary"),
                                      "evidence": [e for f in report.get("findings", []) for e in f.get("evidence", [])][:12],
                                      "written_at": report.get("written_at")},
                   "since": last, "part_logs_since": lines}
        answer, _, _ = _ask(FOLLOWUP_PROMPT, ov.sanitize(payload), 600, search=False)
        if not isinstance(answer, dict) or not str(answer.get("summary") or "").strip():
            raise ValueError("the model's answer had no summary")
        entry = {"at": _iso(time.time()), "by": user, "since": last, "lines_read": len(lines),
                 "summary": str(answer["summary"])[:800], "happened_again": bool(answer.get("happened_again"))}
    except Exception as e:
        why = str(e) if isinstance(e, ov.CapReached) else f"{type(e).__name__}: {str(e)[:160]}"
        return None, f"follow-up could not be written ({why})"
    report = dict(report, followups=list(report.get("followups") or []) + [entry])
    engine.set_report(group, part, report)
    ai_review.save()
    return entry, None
