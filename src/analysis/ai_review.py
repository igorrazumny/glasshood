# File: src/analysis/ai_review.py
# Purpose: REQ-GHA-029 clauses 1-2 — every 3 hours the AI reads each part's recent log lines,
# at the log locations in the landscape files, and names the real problems it finds. Each
# becomes an alarm "found by AI review". The model's text is plain data: it is shown, never
# acted on. Calls count against the overview's daily cap. AI alarms, and any alarm with an
# investigation report, are saved to AI_STATE_DIR so a restart does not drop them. Without a
# writable AI_STATE_DIR they live in memory only, and the status says so plainly.

import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path

from src.analysis import vertex_overview as ov
from src.rules import engine

logger = logging.getLogger(__name__)

WARN_LINES_PER_PART = 40
SAMPLE_LINES_PER_PART = 5
STATE_DIR = os.getenv("AI_STATE_DIR", "")
_STATE_FILE = "saved_alarms.json"
_save_lock = threading.Lock()
_status: dict = {"reviewed_at": None, "error": None, "problems": 0, "parts": 0}
_NOT_SET_UP = "not set up: alarms and reports are kept in memory only and a restart drops them"
_saving: dict = {"durable": False, "problem": _NOT_SET_UP}

REVIEW_PROMPT = """You review the recent log lines of a running cloud system and name its real problems.
You get the parts (id, label, status), the problems still open from earlier reviews, and log lines
per part (warnings and errors first). A real problem is one that hurts users or the service:
repeated errors, failing requests, crashes or restarts, timeouts, running out of memory or disk,
data that could be lost. A single harmless warning, a routine retry that then worked, or a part
that is "not checked" is not a problem. Do not invent problems the lines do not show.
Severity: "critical" only when users are affected now or data can be lost; otherwise "warning".
If a problem is the same as an open one, return that open problem's id; otherwise id is null.
Write titles in plain words for a business reader, at most 12 words, without the part's name.
For each problem also explain it to a business reader, in plain words without log jargon, naming
parts by their label: "what" says what is going wrong, what it affects (the part, and which users
or functions where the lines show it) and how serious it is; "suspicion" is the most likely cause
when the lines point to one, otherwise empty; "directions" are up to 3 other possible causes or
places to look, one sentence each. Say "likely" or "possible": never state a cause as a fact.
Copy evidence lines exactly as given, at most 5 per problem.
Answer in JSON only:
{"problems": [{"id": null, "part": "<part id>", "severity": "critical"|"warning",
 "title": "...", "what": "...", "suspicion": "...", "directions": ["...", ...],
 "evidence": ["<log line>", ...]}]}
Return {"problems": []} when there is nothing real."""


def _new_id(part: str, title: str) -> str:
    return hashlib.sha256(f"{part}|{title}|{time.time()}".encode()).hexdigest()[:10]


def validate(answer, lines_by_part: dict, open_ids: set) -> list:
    """Keep only well-formed problems on a reviewed part whose evidence is among the lines
    the model was shown (so a problem cannot be made up without a log line behind it)."""
    out, seen = [], set()
    for p in (answer or {}).get("problems") or []:
        if not isinstance(p, dict):
            continue
        part, title = p.get("part"), p.get("title")
        if part not in lines_by_part or not isinstance(title, str) or not title.strip():
            continue
        given = set(lines_by_part[part])
        evidence = [e for e in (p.get("evidence") or []) if isinstance(e, str) and e in given][:5]
        if not evidence:
            continue
        severity = p.get("severity") if p.get("severity") in ("critical", "warning") else "warning"
        pid = p.get("id") if isinstance(p.get("id"), str) and p["id"] in open_ids else None
        pid = pid or _new_id(part, title)
        if (pid, part) in seen:
            continue
        seen.add((pid, part))
        out.append({"id": pid, "part": part, "severity": severity,
                    "title": title.strip()[:160], "evidence": evidence, "explanation": _explanation(p)})
    return out


def _explanation(p: dict):
    """REQ-GHA-031: the plain explanation written with the alarm; None without a "what"."""
    text = lambda v, n: v.strip()[:n] if isinstance(v, str) else ""  # noqa: E731
    what = text(p.get("what"), 800)
    if not what:
        return None
    directions = [text(d, 300) for d in (p.get("directions") or []) if text(d, 300)][:3]
    return {"what": what, "suspicion": text(p.get("suspicion"), 400), "directions": directions}


def landscape_names(topology: dict) -> dict:
    """REQ-GHA-031 clause 5: a discovered server sits on the landscape inside its group's box
    (for example "Confidential VM (MIG)"); name it by that box, not by its machine name."""
    _, manifest_labels = ov._manifest_info()
    out = {}
    for n in topology.get("nodes") or []:
        parent = (n.get("metrics") or {}).get("_parent")
        if n.get("id") and parent in manifest_labels:
            out[n["id"]] = manifest_labels[parent]
    return out


def _open_problems() -> list:
    return [{"id": a["group"][3:], "part": a["node_id"], "severity": a["severity"],
             "title": a["title"]} for a in engine.ai_alarms()["active"]]


def run(topology: dict) -> None:
    """One review of every part that has a log location."""
    try:
        parts, lines_by_part, labels = [], {}, {}
        shown_as = landscape_names(topology)
        for rec, log_filter in ov._walk_parts(topology):
            labels[rec["id"]] = shown_as.get(rec["id"], rec["label"])
            parts.append({"id": rec["id"], "label": labels[rec["id"]], "status": rec["status"]})
            if log_filter:
                lines_by_part[rec["id"]] = ov._log_lines(log_filter, WARN_LINES_PER_PART, SAMPLE_LINES_PER_PART)
        if not lines_by_part:
            _status.update(reviewed_at=time.time(), error="no part has a log location", problems=0, parts=0)
            return
        open_problems = _open_problems()
        payload = ov.sanitize({"parts": parts, "open_problems": open_problems, "logs": lines_by_part})
        # The model sees the sanitised lines, so evidence is checked against those
        shown = payload["logs"]
        text, _ = ov.call_model(REVIEW_PROMPT, json.dumps(payload, default=str), max_tokens=3000)
        problems = validate(ov.parse_json(text), shown, {p["id"] for p in open_problems})
        engine.track_ai_review(problems, set(shown), labels)
        _status.update(reviewed_at=time.time(), error=None, problems=len(problems), parts=len(shown))
        logger.info(f"AI log review: {len(problems)} problems on {len(shown)} parts")
        save()
    except Exception as e:
        why = str(e) if isinstance(e, ov.CapReached) else f"{type(e).__name__}: {str(e)[:120]}"
        _status.update(reviewed_at=time.time(), error=why)
        logger.warning(f"AI log review failed: {why}")


def status() -> dict:
    return dict(_status, interval_s=ov.INTERVAL_S, saved=_saving["durable"], saving_problem=_saving["problem"])


# --- Saving (survives a restart when AI_STATE_DIR is a mounted, writable folder) ---

def save() -> bool:
    """Write what must survive a restart. Returns whether it is now on durable storage."""
    if _saving["problem"] and "could not be read" in _saving["problem"]:
        return False
    if not STATE_DIR:
        _saving.update(durable=False, problem=_NOT_SET_UP)
        return False
    with _save_lock:
        try:
            path = Path(STATE_DIR) / _STATE_FILE
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(engine.saved_alarms(), default=str))
            os.replace(tmp, path)
            _saving.update(durable=True, problem=None)
            return True
        except Exception as e:
            _saving.update(durable=False, problem=f"saving failed ({type(e).__name__}): a restart would drop "
                                                  f"alarms and reports")
            logger.error(f"alarms with reports could not be saved: {e}")
            return False


def load() -> None:
    if not STATE_DIR:
        _saving.update(durable=False, problem=_NOT_SET_UP)
        logger.warning("AI_STATE_DIR not set: " + _NOT_SET_UP)
        return
    path = Path(STATE_DIR) / _STATE_FILE
    if path.exists():
        try:
            n = engine.restore_alarms(json.loads(path.read_text()))
            logger.info(f"saved alarms restored: {n}")
        except Exception as e:
            # Keep the unreadable file for a person to look at; do not write over it
            _saving.update(durable=False, problem=f"saved alarms could not be read ({type(e).__name__}); "
                                                  f"the file was left as it is")
            logger.error(f"saved alarms could not be restored: {e}")
            return
    save()  # proves the folder is writable now, so the status is true from the start
