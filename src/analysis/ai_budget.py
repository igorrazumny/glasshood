# File: src/analysis/ai_budget.py
# Purpose: REQ-GHA-041 — each AI provider's spending per calendar month (UTC), kept across
# restarts in AI_STATE_DIR; what is blocked and why; the lines and alarms that say so.

import collections
import json
import logging
import math
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
    """The configured limit; one that makes no sense allows nothing rather than everything."""
    try:
        value = float(os.getenv(f"{provider.upper()}_MONTHLY_LIMIT_USD", "20"))
    except ValueError:
        return 0.0
    return value if math.isfinite(value) and value >= 0 else 0.0


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
    if data.get("month") != _month():
        return _empty()
    for p in (MAIN, BACKUP):
        cost = data[p]["cost"]
        if isinstance(cost, bool) or not isinstance(cost, (int, float)) or not math.isfinite(cost) or cost < 0:
            raise ValueError("a monthly total is not a valid amount")
    return data


def _write(data: dict) -> None:
    path = _path()
    fd, tmp = tempfile.mkstemp(prefix=".ai_budget.", dir=os.path.dirname(path))
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)


class Blocked(RuntimeError):
    """A paid call may not go out; the message says why in words."""


def reserve(provider: str, usd: float) -> tuple:
    """Put a call's most possible cost on disk before it goes out. If that cannot be done, the
    call is not made. What is reserved survives a crash; settle() corrects it to the real cost."""
    with _lock:
        try:
            data = _read()
            data[provider]["cost"] = round(data[provider]["cost"] + usd, 6)
            _write(data)
            return provider, usd, data["month"]
        except Exception as e:
            raise Blocked(f"its monthly total could not be saved ({type(e).__name__})") from None


def settle(reservation: tuple, actual: float, answered: bool = True) -> None:
    """Replace a reservation by the real cost in the month it was made. If this cannot be
    written, the higher reserved amount simply stays."""
    provider, usd, month = reservation
    with _lock:
        try:
            data = _read()
            if data["month"] != month:
                return
            data[provider]["cost"] = round(max(0.0, data[provider]["cost"] - usd + actual), 6)
            if answered:
                data[provider]["refused"] = None
            _write(data)
        except Exception as e:
            logger.warning(f"an AI cost could not be corrected; the reserved amount stands ({type(e).__name__})")


def release(reservation: tuple) -> None:
    """The provider did not take the request, so it costs nothing."""
    settle(reservation, 0.0, answered=False)


def charge(provider: str, usd: float) -> None:
    """Add a known cost directly."""
    settle(reserve(provider, usd), usd)


def refused(provider: str, reason: str) -> None:
    """The provider itself turned GlassHood away (credit, quota, billing or key)."""
    with _lock:
        try:
            data = _read()
            data[provider]["refused"] = reason
            _write(data)
        except Exception:
            pass                 # the refusal repeats on the next call; the line below still says it
    note(f"AI provider {NAMES[provider]} is blocked: {reason}.")


def gate(provider: str):
    """Why no paid call may go to this provider, or None."""
    with _lock:
        try:
            data = _read()
        except Exception as e:
            return str(e) if isinstance(e, OSError) else f"its monthly total could not be read ({type(e).__name__})"
        try:
            _write(data)     # it must also be possible to save the next call's cost
        except Exception as e:
            return f"its monthly total could not be saved ({type(e).__name__})"
        spent = data[provider]["cost"]
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


_was_blocked: set = set()
_since_here = [None]             # when AI went offline, if it could not be saved


def offline_since():
    """When AI went offline (kept across restarts), or None while it is not offline."""
    with _lock:
        try:
            return _read().get("offline_since") or _since_here[0]
        except Exception:
            return _since_here[0]


def _mark_offline(offline: bool) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _lock:
        _since_here[0] = (_since_here[0] or now) if offline else None
        try:
            data = _read()
            if bool(data.get("offline_since")) != offline:
                data["offline_since"] = (data.get("offline_since") or _since_here[0]) if offline else None
                _write(data)
        except Exception:
            pass


def monitor() -> None:
    """Say every block and recovery in the log without needing a paid call to notice it."""
    st = status()
    blocked = {p for p, v in st.items() if v["blocked"]}
    _mark_offline(blocked == {MAIN, BACKUP})
    for p in blocked:
        note(f"AI provider {NAMES[p]} is blocked: {st[p]['blocked']}.")
    if MAIN in blocked and BACKUP not in blocked:
        note("GlassHood is using its backup AI provider, Anthropic, because OpenAI is blocked.")
    for p in _was_blocked - blocked:
        note(f"AI provider {NAMES[p]} is no longer blocked.")
    if _was_blocked - blocked:
        with _lock:
            _logged.clear()     # a block that returns is a new episode and is said again
    _was_blocked.clear()
    _was_blocked.update(blocked)


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
                                         f"Spent this month: {amounts}. The last evaluations stay on screen. " + (
                                             f"AI evaluations resume on {resumes()}, or earlier if the administrator raises a limit."
                                             if "monthly limit" in main["blocked"] and "monthly limit" in backup["blocked"]
                                             else "AI evaluations resume only once the administrator resolves these blocks."),
                                 "suspicion": "", "directions": ["Administrator: raise a monthly limit, or resolve the provider's credit, billing or key problem."]}}]
    return [{"group": "budget:openai", "title": f"{NAMES[MAIN]} is blocked: GlassHood is running on its backup, {NAMES[BACKUP]}",
             "explanation": {"what": f"{NAMES[MAIN]}, the main AI provider, is blocked: {main['blocked']}. AI evaluations continue on {NAMES[BACKUP]}. "
                                     f"Spent this month: {amounts}. The administrator must act.",
                             "suspicion": "", "directions": [f"Administrator: raise the {NAMES[MAIN]} monthly limit, or resolve its credit, billing or key problem."]}}]
