# File: src/analysis/ai_budget.py
# Purpose: REQ-GHA-041 — each AI provider's spending per calendar month (UTC), kept across
# restarts in AI_STATE_DIR; what is blocked and why; the lines and alarms that say so.

import collections
import json
import logging
import os
import tempfile
import threading
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

MAIN, BACKUP = "openai", "anthropic"
NAMES = {MAIN: "OpenAI", BACKUP: "Anthropic"}
ALARM_PART = "gls-ai-overview"   # the box of GlassHood's own AI work on its landscape
GROUP = "glasshood"              # the product whose card carries the notice
_LOG_EVERY_S = 3600

_lock = threading.Lock()
_logged: dict = {}               # what -> when it was last logged
_lines: collections.deque = collections.deque(maxlen=40)


def limit(provider: str) -> float:
    return float(os.getenv(f"{provider.upper()}_MONTHLY_LIMIT_USD", "20"))


def _month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def resumes() -> str:
    now = datetime.now(timezone.utc)
    first = datetime(now.year + (now.month == 12), now.month % 12 + 1, 1)
    return first.strftime("%-d %b %Y") + " (UTC)"


def _path():
    d = os.getenv("AI_STATE_DIR", "")
    return os.path.join(d, "ai_budget.json") if d else None


def _empty() -> dict:
    return {"month": _month(), MAIN: {"cost": 0.0, "refused": None}, BACKUP: {"cost": 0.0, "refused": None}}


def _read() -> dict:
    """This month's totals. Raises when they cannot be read: the caller then makes no paid call."""
    path = _path()
    if not path:
        raise OSError("no folder is set up to keep the monthly AI totals (AI_STATE_DIR)")
    if not os.path.isdir(os.path.dirname(path)) or not os.access(os.path.dirname(path), os.W_OK):
        raise OSError("the folder that keeps the monthly AI totals is not writable")
    if not os.path.exists(path):
        return _empty()
    with open(path) as f:
        data = json.load(f)
    return data if data.get("month") == _month() else _empty()


def _write(data: dict) -> None:
    path = _path()
    fd, tmp = tempfile.mkstemp(prefix=".ai_budget.", dir=os.path.dirname(path))
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)


_unsaved: dict = {}              # provider -> why its total could not be saved


def charge(provider: str, usd: float) -> None:
    """Add one answered call; an answer also ends any refusal by that provider."""
    with _lock:
        try:
            data = _read()
            data[provider]["cost"] = round(data[provider]["cost"] + usd, 6)
            data[provider]["refused"] = None
            _write(data)
            _unsaved.pop(provider, None)
        except Exception as e:
            _unsaved[provider] = f"its monthly total could not be saved ({type(e).__name__})"


def refused(provider: str, reason: str) -> None:
    """The provider itself turned GlassHood away (credit, quota, billing or key)."""
    with _lock:
        try:
            data = _read()
            data[provider]["refused"] = reason
            _write(data)
        except Exception as e:
            _unsaved[provider] = f"its monthly total could not be saved ({type(e).__name__})"
    note(f"AI provider {NAMES[provider]} is blocked: {reason}.")


def gate(provider: str):
    """Why no paid call may go to this provider, or None."""
    with _lock:
        if provider in _unsaved:
            return _unsaved[provider]
        try:
            spent = _read()[provider]["cost"]
        except Exception as e:
            return str(e) if isinstance(e, OSError) else f"its monthly total could not be read ({type(e).__name__})"
    if spent >= limit(provider):
        return f"its monthly limit of ${limit(provider):.2f} is reached (${spent:.2f} spent this month)"
    return None


def status() -> dict:
    """{provider: {spent, limit, blocked}}; blocked is the reason in words, or None."""
    with _lock:
        try:
            data = _read()
        except Exception:
            data = None
    out = {}
    for p in (MAIN, BACKUP):
        entry = (data or {}).get(p) or {}
        why = gate(p) or entry.get("refused")
        if p == BACKUP and not os.getenv("ANTHROPIC_API_KEY") and not why:
            why = "no key is configured"
        out[p] = {"spent": round(entry.get("cost", 0.0), 4), "limit": limit(p), "blocked": why}
    return out


def note(line: str) -> None:
    """Log a block in plain words, at most hourly for the same words; the AI log review reads these."""
    now = time.time()
    with _lock:
        if now - _logged.get(line, 0) < _LOG_EVERY_S:
            return
        _logged[line] = now
        _lines.append(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} WARNING {line}")
    logger.warning(line)


def recent_lines() -> list:
    with _lock:
        return list(_lines)


def alarms() -> list:
    """The critical alarms in force. No AI call is involved in writing them."""
    st = status()
    main, backup = st[MAIN], st[BACKUP]
    if not main["blocked"]:
        return []
    amounts = f"{NAMES[MAIN]} ${main['spent']:.2f} of ${main['limit']:.2f}, {NAMES[BACKUP]} ${backup['spent']:.2f} of ${backup['limit']:.2f}"
    if backup["blocked"]:
        return [{"group": "budget:all", "title": "AI evaluations have stopped: both AI providers are blocked",
                 "explanation": {"what": f"GlassHood can make no AI call. {NAMES[MAIN]}: {main['blocked']}. {NAMES[BACKUP]}: {backup['blocked']}. "
                                         f"Spent this month: {amounts}. The last evaluations stay on screen. "
                                         f"AI evaluations resume on {resumes()}, or earlier once the administrator resolves a block.",
                                 "suspicion": "", "directions": ["Administrator: raise a monthly limit, or resolve the provider's credit, billing or key problem."]}}]
    return [{"group": "budget:openai", "title": f"{NAMES[MAIN]} is blocked: GlassHood is running on its backup, {NAMES[BACKUP]}",
             "explanation": {"what": f"{NAMES[MAIN]}, the main AI provider, is blocked: {main['blocked']}. AI evaluations continue on {NAMES[BACKUP]}. "
                                     f"Spent this month: {amounts}. The administrator must act.",
                             "suspicion": "", "directions": [f"Administrator: raise the {NAMES[MAIN]} monthly limit, or resolve its credit, billing or key problem."]}}]
