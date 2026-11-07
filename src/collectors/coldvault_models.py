# File: src/collectors/coldvault_models.py
# Purpose: REQ-GHA-034 — which of ColdVault's AI models failed in the last hour, why,
# and which model answered in its place.
#
# Two read-only sources, nothing changed in ColdVault:
#   - ColdVault's /api/metrics requests.per_model: answered / failed / timed_out per
#     model id over the last hour (read by src/collectors/coldvault.py);
#   - ColdVault's own log lines, where the landscape file's alarm_sources.models says:
#     "<Provider> stream failed: <Model> - <reason>" (ERROR), "Fallback: <Model> failed
#     (<reason>), trying <Backup>" (INFO) and the "billing" line of every model that
#     answered, all carrying the request_id of the question.
#
# A provider box in the landscape names the providers it stands for:
#   monitoring: {probe: {type: coldvault_models, providers: [claude, gemini]}}

import json
import logging
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_state: dict = {"read": False, "reason": "not read yet", "checked_at": None, "models": {}}

# The same prefixes ColdVault uses to tell a model's provider from its id
_PREFIXES = (("dashscope", "dashscope"), ("redpill", "redpill"), ("vllm", "vllm"),
             ("gemini", "gemini"), ("gpt", "openai"), ("claude", "claude"),
             ("xai/", "grok"), ("grok", "grok"), ("qwen", "qwen"))

_FAILED = re.compile(r"stream failed: (?P<model>.+?) - (?P<reason>.+)$", re.S)
_FALLBACK = re.compile(r"Fallback: (?P<model>.+?) failed \((?P<reason>.*)\), trying (?P<backup>.+?)\s*$", re.S)


def provider_of(model_id: str) -> str:
    low = (model_id or "").lower()
    for prefix, provider in _PREFIXES:
        if low.startswith(prefix):
            return provider
    return "unknown"


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


def _id_for(name: str, ids) -> Optional[str]:
    """The model id a display name ("Claude Opus 4.7") stands for ("claude-opus-4-7")."""
    n = _norm(name)
    for model_id in ids:
        m = _norm(model_id)
        if m == n or m.endswith("-" + n) or n.endswith("-" + m):
            return model_id
    return None


def plain_reason(reason: str) -> str:
    """A short reason a business reader understands, from the provider's error text."""
    r = (reason or "").lower()
    if "429" in r or "quota" in r or "rate limit" in r or "ratelimit" in r:
        return "usage limit reached (429, quota exceeded)"
    if "timeout" in r or "timed out" in r:
        return "no answer in time (timeout)"
    if "401" in r or "403" in r or "permission" in r or "unauthor" in r:
        return "access refused by the provider (401/403)"
    if re.search(r"\b5\d\d\b", r) or "unavailable" in r or "overloaded" in r:
        return "provider error (5xx, unavailable)"
    first = (reason or "").strip().splitlines()[0] if (reason or "").strip() else ""
    return first[:120] or "no reason given"


def _source() -> Optional[dict]:
    """alarm_sources.models from the landscape file: {project, filter} of the app's own lines."""
    from src.collectors.alarm_sources import _environments
    for _, env in _environments():
        declared = (env.get("alarm_sources") or {}).get("models")
        if isinstance(declared, dict) and declared.get("project") and declared.get("filter"):
            return {"project": declared["project"], "filter": declared["filter"]}
    return None


def _read_lines(project: str, log_filter: str, max_entries: int = 200) -> list[dict]:
    """The app's JSON lines matching the filter in the last hour, newest first."""
    from google.cloud.logging_v2 import Client
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    entries = Client(project=project).list_entries(
        filter_=f'({log_filter}) AND timestamp>="{cutoff}"', order_by="timestamp desc",
        max_results=max_entries)
    lines = []
    for e in entries:
        p = e.payload if isinstance(e.payload, dict) else {}
        raw = p.get("message", "")
        try:
            line = json.loads(raw) if isinstance(raw, str) and raw.startswith("{") else {"message": raw}
        except ValueError:
            line = {"message": raw}
        line["_raw"] = raw
        line.setdefault("timestamp", str(e.timestamp))
        lines.append(line)
    return lines


def _events(per_model: dict, lines: list[dict]) -> dict:
    """Per failing model id: last reason, request ids (with the failure time and the
    backup tried for each), the latest time and the evidence lines."""
    ids = list(per_model)
    out: dict = {}
    for line in lines:
        msg = str(line.get("message", ""))
        for pattern, kind in ((_FALLBACK, "fallback"), (_FAILED, "failed")):
            m = pattern.search(msg)
            if not m:
                continue
            model_id = _id_for(m.group("model"), ids) or _norm(m.group("model"))
            ev = out.setdefault(model_id, {"name": m.group("model").strip(), "reason": None,
                                           "requests": set(), "backup_by_request": {}, "at_by_request": {},
                                           "last_at": None, "evidence": []})
            # lines are newest first: the first reason and time seen are the latest
            if ev["reason"] is None:
                ev["reason"] = m.group("reason").strip()
            rid = line.get("request_id")
            if rid:
                ev["requests"].add(rid)
                ev["at_by_request"].setdefault(rid, line.get("timestamp"))
                if kind == "fallback":
                    ev["backup_by_request"].setdefault(rid, m.group("backup").strip())
            ev["last_at"] = ev["last_at"] or line.get("timestamp")
            if len(ev["evidence"]) < 20:
                ev["evidence"].append(line.get("_raw") or msg)
            break
    return out


_MAX_REQUESTS = 20   # questions whose outcome is looked up per reading
_MAX_LINES = 200     # lines read per query; a full page may hide older lines
_HOUR = 3600
# Request-level outcomes already established: request_id -> {model, outcome, answered_by, at, read_at}.
# Reused only for questions of the last hour, when a later reading of the lines fails.
_facts: dict = {}


def _ts(value) -> Optional[float]:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def _outcomes(model_id: str, ev: dict, billing: list[dict], looked_up: set) -> dict:
    """What happened to each question this model failed, judged per request_id (never
    from hourly totals). ColdVault writes one billing line per question, naming the model
    the user chose, with how many model answers it completed: completed > 0 means the
    question was answered (by the backup named in that question's switch-to-backup line,
    or by this model itself on a retry when no backup was tried). A question whose billing
    line was certainly read (looked_up) and is missing or completed nothing got no reply;
    any other question's outcome is unknown. Returns the counts and per-request facts."""
    completed: dict = {}
    for line in billing:
        rid = line.get("request_id")
        if rid in ev["requests"]:
            done = line.get("completed")
            completed[rid] = max(completed.get(rid, 0), done if isinstance(done, int) else 1)
    facts = {}
    for rid in ev["requests"]:
        if completed.get(rid, 0) > 0:
            # no backup tried for this question: the model itself answered on a retry
            by = ev["backup_by_request"].get(rid)
            facts[rid] = {"model": model_id, "outcome": "answered" if by else "retried", "answered_by": by}
        elif rid in looked_up:
            facts[rid] = {"model": model_id, "outcome": "no reply", "answered_by": None}
        else:
            continue
        facts[rid]["at"] = _ts(ev["at_by_request"].get(rid))
    return _counts(facts)


def _counts(facts: dict) -> dict:
    answered = [f for f in facts.values() if f["outcome"] == "answered"]
    retried = sum(1 for f in facts.values() if f["outcome"] == "retried")
    return {"recovered": len(answered) + retried, "retried": retried,
            "unanswered": sum(1 for f in facts.values() if f["outcome"] == "no reply"),
            "backups": sorted({f["answered_by"] for f in answered}),
            "facts": facts}


def refresh(metrics: dict, metrics_status: dict, read_lines=_read_lines) -> None:
    """Rebuild the per-model picture from ColdVault's latest metrics and its log lines."""
    checked_at = time.time()
    per_model = ((metrics or {}).get("requests") or {}).get("per_model") if metrics_status.get("read") else None
    if not isinstance(per_model, dict):
        reason = ("ColdVault does not report per-model figures yet" if metrics_status.get("read")
                  else f"ColdVault's figures were not read: {metrics_status.get('reason') or 'unknown'}")
        with _lock:
            _state.update(read=False, reason=reason, checked_at=checked_at, models={})
        return

    failing = [m for m, c in per_model.items() if (c.get("failed", 0) + c.get("timed_out", 0)) > 0]
    events, billing, looked_up, lines_reason = {}, [], set(), ""
    src = _source() if failing else None
    if failing and src:
        try:
            lines = read_lines(src["project"],
                               f'({src["filter"]}) AND (jsonPayload.message:"stream failed" '
                               f'OR jsonPayload.message:"Fallback:")', _MAX_LINES)
            events = _events(per_model, lines)
            requests = sorted({r for ev in events.values() for r in ev["requests"]})[:_MAX_REQUESTS]
            if requests:
                ors = " OR ".join(f'jsonPayload.message:"{r}"' for r in requests)
                raw = read_lines(src["project"],
                                 f'({src["filter"]}) AND jsonPayload.message:"billing" AND ({ors})', _MAX_LINES)
                billing = [l for l in raw if l.get("event") == "billing" or l.get("message") == "billing"]
                # A full page may hide older billing lines: then only the questions whose
                # billing line was seen count as looked up, the rest stay unknown
                looked_up = set(requests) if len(raw) < _MAX_LINES else {l.get("request_id") for l in billing}
        except Exception as e:
            events, billing, looked_up = {}, [], set()
            lines_reason = f"ColdVault's log lines were not read ({type(e).__name__})"
            logger.warning(f"model failures: {lines_reason}: {e}")
    elif failing:
        lines_reason = "no log source for model lines in the landscape file"

    hour_ago = checked_at - _HOUR
    with _lock:
        previous = dict(_state.get("models") or {})
        for rid in [r for r, f in _facts.items() if (f.get("at") or 0) < hour_ago]:
            del _facts[rid]
    models = {}
    for model_id, c in per_model.items():
        failed = c.get("failed", 0) + c.get("timed_out", 0)
        entry = {"id": model_id, "provider": provider_of(model_id),
                 "answered": c.get("answered", 0), "failed": c.get("failed", 0),
                 "timed_out": c.get("timed_out", 0)}
        if failed:
            ev = events.get(model_id)
            old = previous.get(model_id) or {}
            if ev:
                out = _outcomes(model_id, ev, billing, looked_up)
                with _lock:
                    for rid, f in out["facts"].items():
                        _facts[rid] = {**f, "read_at": checked_at}
                entry.update(name=ev["name"], reason=plain_reason(ev["reason"]) if ev["reason"] else "no reason given",
                             last_at=ev["last_at"], evidence=ev["evidence"], outcome_note="", **out)
            else:
                # Lines not read now: only questions of the last hour established by an earlier
                # reading are reused, as earlier facts; nothing is assigned to newer failures
                with _lock:
                    kept = {r: f for r, f in _facts.items()
                            if f["model"] == model_id and (f.get("at") or 0) >= hour_ago}
                out = _counts(kept)
                note = lines_reason or "no failure lines found for this model"
                if kept:
                    read_at = max(f["read_at"] for f in kept.values())
                    note += (f"; {_plural(len(kept), 'outcome')} from the reading at "
                             f"{datetime.fromtimestamp(read_at, timezone.utc).strftime('%H:%M')} UTC")
                entry.update(name=old.get("name") or model_id,
                             reason=old.get("reason") or "no reason found in the log lines",
                             last_at=old.get("last_at"), evidence=old.get("evidence") or [],
                             outcome_note=note, **out)
            entry.pop("facts", None)
            entry["unknown"] = max(0, failed - entry["recovered"] - entry["unanswered"])
            entry["backup"] = ", ".join(entry.get("backups") or []) or None
        models[model_id] = entry
    with _lock:
        _state.update(read=True, reason="", checked_at=checked_at, models=models)


def snapshot() -> dict:
    with _lock:
        return {**_state, "models": {k: dict(v) for k, v in _state["models"].items()}}


def box(providers: list) -> dict:
    """Status, figures and a plain description for a provider box (clauses 1, 2 and 8)."""
    s = snapshot()
    if not s["read"]:
        return {"status": "not checked", "metrics": {"note": s["reason"]}, "check_description": s["reason"]}
    wanted = {p.lower() for p in providers or []}
    models = [m for m in s["models"].values() if m["provider"] in wanted]
    calls = sum(m["answered"] + m["failed"] + m["timed_out"] for m in models)
    if not models or calls == 0:
        return {"status": "idle", "metrics": {"models": []},
                "check_description": "No calls to these models in the last hour (idle)"}
    failing = [m for m in models if m["failed"] + m["timed_out"] > 0]
    if not failing:
        status = "healthy"
    elif any(m.get("unanswered") for m in failing):
        status = "error"
    else:
        status = "degraded"
    lines = [_model_sentence(m) for m in sorted(failing, key=lambda m: m["id"])]
    desc = " ".join(lines) if lines else "Every call in the last hour was answered."
    return {"status": status, "metrics": {"models": sorted(models, key=lambda m: m["id"])},
            "check_description": desc}


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'s' if n != 1 else ''}"


def _outcome_words(m: dict) -> str:
    """What happened to the questions this model failed, from per-question evidence."""
    parts = []
    by_backup = (m.get("recovered") or 0) - (m.get("retried") or 0)
    if by_backup:
        parts.append(f"{m.get('backup') or 'another model'} answered {_plural(by_backup, 'question')} in its place")
    if m.get("retried"):
        parts.append(f"it answered {_plural(m['retried'], 'question')} itself on a retry")
    if m.get("unanswered"):
        parts.append(f"{_plural(m['unanswered'], 'question')} got no reply from any model")
    if m.get("unknown"):
        parts.append(f"for {_plural(m['unknown'], 'failed call')} it is not known whether another model answered")
    words = "; ".join(parts)
    # The note (lines not read, outcomes from an earlier reading) is shown whenever there is one
    return f"{words} ({m['outcome_note']})" if m.get("outcome_note") else words


def _model_sentence(m: dict) -> str:
    n = m["failed"] + m["timed_out"]
    return (f"{m.get('name') or m['id']} failed {_plural(n, 'time')} in the last hour ({m.get('reason')}); "
            f"{_outcome_words(m)}.")


def failures(provider_parts: dict) -> list:
    """One entry per failing model for the alarm engine: part, severity, title, explanation.
    Critical only when a question is known to have got no reply; a warning otherwise."""
    s = snapshot()
    out = []
    for m in s["models"].values():
        n = m["failed"] + m["timed_out"]
        part = provider_parts.get(m["provider"])
        if not n or not part:
            continue
        name, backup, reason = m.get("name") or m["id"], m.get("backup"), m.get("reason")
        words = _outcome_words(m)
        what = f"{name} failed {_plural(n, 'time')} in the last hour ({reason}). {words[:1].upper()}{words[1:]}."
        if m.get("unanswered"):
            severity, tail = "critical", f"{_plural(m['unanswered'], 'question')} got no reply"
            what += " Those users got no answer."
        elif m.get("recovered") and not m.get("unknown") and not backup:
            severity, tail = "warning", "it answered on a retry"
            what += " Users still got a reply."
        elif m.get("recovered") and not m.get("unknown"):
            severity, tail = "warning", f"{backup} answered instead"
            what += " Users still got a reply, possibly from a different model than they chose."
        elif m.get("recovered"):
            severity, tail = "warning", (f"{backup} answered some questions in its place" if backup
                                         else "some questions were answered on a retry")
        else:
            severity, tail = "warning", "whether another model answered is not known"
        suspicion, directions = _where_to_look(reason, name)
        out.append({
            "model": m["id"], "part": part, "severity": severity,
            "title": f"{name} is failing; {tail}",
            "explanation": {"what": what, "suspicion": suspicion, "directions": directions},
            "evidence": m.get("evidence") or [],
        })
    return out


def _where_to_look(reason: str, name: str) -> tuple:
    r = reason or ""
    if "429" in r:
        return (f"The provider's usage limit for {name} is likely reached.",
                [f"Check the quota for {name} in the provider's console and ask for more if it is too low.",
                 "Check whether traffic or the size of questions grew, so more tokens are used per minute.",
                 "Check that the backup model has enough quota of its own."])
    if "timeout" in r:
        return (f"{name} is likely slow or overloaded at the provider.",
                ["Check the provider's status page.", "Compare answer times of this model over the last hours."])
    if "401" in r:
        return ("ColdVault's access to the provider is possibly refused or expired.",
                ["Check the key or the account permission ColdVault uses for this provider."])
    if "5xx" in r:
        return ("The provider likely has a problem on its side.",
                ["Check the provider's status page.", "Watch whether the failures stop by themselves."])
    return (None, ["Open the related log lines to see the provider's own error message."])


def provider_parts() -> dict:
    """{provider: box id} from the landscape's provider boxes (probe type coldvault_models)."""
    from src.collectors.alarm_sources import _environments
    parts = {}
    for _, env in _environments():
        for node in env.get("nodes") or []:
            probe = ((node.get("monitoring") or {}).get("probe") or {})
            if probe.get("type") == "coldvault_models":
                for provider in probe.get("providers") or []:
                    parts.setdefault(str(provider).lower(), node.get("id"))
    return parts
