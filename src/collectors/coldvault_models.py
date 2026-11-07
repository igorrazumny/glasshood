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
    """Per failing model id: last reason, backup, request ids, time and the evidence lines."""
    ids = list(per_model)
    out: dict = {}
    for line in lines:
        msg = str(line.get("message", ""))
        for pattern, kind in ((_FALLBACK, "fallback"), (_FAILED, "failed")):
            m = pattern.search(msg)
            if not m:
                continue
            model_id = _id_for(m.group("model"), ids) or _norm(m.group("model"))
            ev = out.setdefault(model_id, {"name": m.group("model").strip(), "reason": None, "backup": None,
                                           "requests": set(), "last_at": None, "evidence": []})
            # lines are newest first: the first reason and time seen are the latest
            if ev["reason"] is None:
                ev["reason"] = m.group("reason").strip()
            if kind == "fallback" and ev["backup"] is None:
                ev["backup"] = m.group("backup").strip()
            if line.get("request_id"):
                ev["requests"].add(line["request_id"])
            ev["last_at"] = ev["last_at"] or line.get("timestamp")
            if len(ev["evidence"]) < 20:
                ev["evidence"].append(line.get("_raw") or msg)
            break
    return out


def _answered_elsewhere(model_id: str, ev: dict, per_model: dict, billing: list[dict]) -> Optional[str]:
    """The model that answered a question this model failed, or None (users got no reply)."""
    for line in billing:
        other = line.get("model")
        if line.get("request_id") in ev["requests"] and other and _id_for(other, [model_id]) is None:
            return other
    backup = ev.get("backup")
    if backup:
        backup_id = _id_for(backup, per_model)
        if backup_id and (per_model.get(backup_id) or {}).get("answered", 0) > 0:
            return backup
    return None


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
    events, billing, lines_reason = {}, [], ""
    src = _source() if failing else None
    if failing and src:
        try:
            lines = read_lines(src["project"],
                               f'({src["filter"]}) AND (jsonPayload.message:"stream failed" '
                               f'OR jsonPayload.message:"Fallback:")')
            events = _events(per_model, lines)
            requests = sorted({r for ev in events.values() for r in ev["requests"]})[:20]
            if requests:
                ors = " OR ".join(f'jsonPayload.message:"{r}"' for r in requests)
                billing = [l for l in read_lines(src["project"],
                                                 f'({src["filter"]}) AND jsonPayload.message:"billing" AND ({ors})')
                           if l.get("event") == "billing" or l.get("message") == "billing"]
        except Exception as e:
            lines_reason = f"ColdVault's log lines were not read ({type(e).__name__})"
            logger.warning(f"model failures: {lines_reason}: {e}")
    elif failing:
        lines_reason = "no log source for model lines in the landscape file"

    models = {}
    for model_id, c in per_model.items():
        failed = c.get("failed", 0) + c.get("timed_out", 0)
        entry = {"id": model_id, "provider": provider_of(model_id),
                 "answered": c.get("answered", 0), "failed": c.get("failed", 0),
                 "timed_out": c.get("timed_out", 0)}
        if failed:
            ev = events.get(model_id) or {}
            entry.update(name=ev.get("name") or model_id,
                         reason=plain_reason(ev.get("reason")) if ev.get("reason") else (lines_reason or "no reason found in the log lines"),
                         backup=_answered_elsewhere(model_id, ev, per_model, billing) if ev else None,
                         last_at=ev.get("last_at"), evidence=ev.get("evidence") or [])
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
    elif any(not m.get("backup") for m in failing):
        status = "error"
    else:
        status = "degraded"
    lines = [_model_sentence(m) for m in sorted(failing, key=lambda m: m["id"])]
    desc = " ".join(lines) if lines else "Every call in the last hour was answered."
    return {"status": status, "metrics": {"models": sorted(models, key=lambda m: m["id"])},
            "check_description": desc}


def _model_sentence(m: dict) -> str:
    n = m["failed"] + m["timed_out"]
    s = f"{m.get('name') or m['id']} failed {n} time{'s' if n != 1 else ''} in the last hour ({m.get('reason')})"
    s += f"; {m['backup']} answered in its place." if m.get("backup") else "; no other model answered."
    return s


def failures(provider_parts: dict) -> list:
    """One entry per failing model for the alarm engine: part, severity, title, explanation."""
    s = snapshot()
    out = []
    for m in s["models"].values():
        n = m["failed"] + m["timed_out"]
        part = provider_parts.get(m["provider"])
        if not n or not part:
            continue
        name, backup, reason = m.get("name") or m["id"], m.get("backup"), m.get("reason")
        if backup:
            what = (f"{name} failed {n} time{'s' if n != 1 else ''} in the last hour ({reason}). "
                    f"{backup} answered in its place, so users still got a reply, possibly from a different model than they chose.")
        else:
            what = (f"{name} failed {n} time{'s' if n != 1 else ''} in the last hour ({reason}) "
                    f"and no other model answered, so those questions got no reply.")
        suspicion, directions = _where_to_look(reason, name)
        out.append({
            "model": m["id"], "part": part, "severity": "warning" if backup else "critical",
            "title": f"{name} is failing" + (f"; {backup} answered instead" if backup else "; no other model answered"),
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
