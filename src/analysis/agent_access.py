# File: src/analysis/agent_access.py
# Purpose: REQ-GHA-049: what agents need that outlives a restart: each agent's credential (only its
#   hash), the feed of changes with each agent's position in it, and the corrections agents submitted.

import copy
import hashlib
import json
import logging
import os
import secrets
import tempfile
import threading
import time

logger = logging.getLogger(__name__)

MAX_EVENTS = 5000
STARTUP_GRACE_S = 600   # after a restart the alarms are rebuilt: an alarm is not called ended until they are
WORDS = {"normal": "Healthy", "attention": "Needs attention", "failing": "Degraded"}

_lock = threading.RLock()
_state: dict = {}
_loaded = [False]
_started = [None]


class Unavailable(Exception):
    """The agents' state could not be read or saved."""


def _file():
    d = os.getenv("AI_STATE_DIR", "")
    return os.path.join(d, "agent_access.json") if d else None


def _load() -> None:
    if _loaded[0]:
        return
    path = _file()
    if not path:
        raise Unavailable("no folder is set up to keep the agents' state (AI_STATE_DIR)")
    try:
        saved = {}
        if os.path.exists(path):
            with open(path) as f:
                saved = json.load(f)
    except (OSError, ValueError) as e:
        raise Unavailable(f"the agents' state could not be read ({type(e).__name__})") from None
    _state.clear()
    _state.update({"keys": {}, "positions": {}, "events": [], "next": 1, "snapshot": {}, "corrections": [], **saved})
    _loaded[0] = True


def _save() -> None:
    path = _file()
    try:
        fd, tmp = tempfile.mkstemp(prefix=".agent_access.", dir=os.path.dirname(path))
        with os.fdopen(fd, "w") as f:
            json.dump(_state, f)
        os.replace(tmp, path)
    except OSError as e:
        raise Unavailable(f"the agents' state could not be saved ({type(e).__name__})") from None


def _commit(before: dict) -> None:
    """Saved, or nothing happened: a failed save leaves memory as it was, so no change is lost."""
    try:
        _save()
    except Unavailable:
        _state.clear()
        _state.update(before)
        raise


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def create_key(agent: str) -> str:
    """A new credential replaces the agent's old one. Only its hash is kept."""
    key = "gha_" + secrets.token_urlsafe(32)
    with _lock:
        _load()
        before = copy.deepcopy(_state)
        _state["keys"] = {h: v for h, v in _state["keys"].items() if v["agent"] != agent}
        _state["keys"][_hash(key)] = {"agent": agent, "created": time.time()}
        _commit(before)
    return key


def withdraw_key(agent: str) -> bool:
    with _lock:
        _load()
        before = copy.deepcopy(_state)
        kept = {h: v for h, v in _state["keys"].items() if v["agent"] != agent}
        changed = len(kept) != len(_state["keys"])
        _state["keys"] = kept
        _commit(before)
    return changed


def agent_of(key: str):
    with _lock:
        _load()
        return (_state["keys"].get(_hash(key)) or {}).get("agent")


def status_word(record) -> str:
    return WORDS.get((record or {}).get("condition"), "Not yet assessed")


def _add(now, system, kind, **more) -> None:
    _state["events"].append({"seq": _state["next"], "at": now, "system": system, "kind": kind, **more})
    _state["next"] += 1


def record_changes(records: dict, alerts_by_system: dict, now: float = None) -> None:
    """Clause 4. Only systems with a saved record are compared; a restart produces no changes."""
    now = time.time() if now is None else now
    if _started[0] is None:
        _started[0] = now
    settled = now - _started[0] >= STARTUP_GRACE_S
    with _lock:
        _load()
        previous = copy.deepcopy(_state)
        changed = False
        for system, record in records.items():
            if not (record or {}).get("condition"):
                continue
            word = status_word(record)
            alerts = {str(a.get("number")): {"title": a.get("title"), "level": a.get("severity")}
                      for a in alerts_by_system.get(system) or []}
            before = _state["snapshot"].get(system)
            if before is not None:
                if before["status"] != word:
                    _add(now, system, "status_changed", before=before["status"], after=word)
                    changed = True
                for number, a in alerts.items():
                    if number not in before["alerts"]:
                        _add(now, system, "alert_new", number=number, **a)
                        changed = True
                for number, a in before["alerts"].items():
                    if number in alerts:
                        continue
                    if settled:
                        _add(now, system, "alert_ended", number=number, **a)
                        changed = True
                    else:       # alarms still being rebuilt: kept until it is known whether it really ended
                        alerts[number] = a
            if before != {"status": word, "alerts": alerts}:
                _state["snapshot"][system] = {"status": word, "alerts": alerts}
                changed = True
        if changed:
            _state["events"] = _state["events"][-MAX_EVENTS:]
            _commit(previous)


def missed(agent: str, system: str = None) -> bool:
    """Older changes were discarded before this agent read them: it should re-read the current state."""
    with _lock:
        _load()
        since = _state["positions"].get(f"{agent}|{system or '*'}", 0)
        return bool(_state["events"]) and _state["events"][0]["seq"] > since + 1


def changes_for(agent: str, system: str = None) -> list:
    """Each change once, per agent and per scope; the position is saved before the answer leaves."""
    scope = f"{agent}|{system or '*'}"
    with _lock:
        _load()
        since = _state["positions"].get(scope, 0)
        out = [e for e in _state["events"] if e["seq"] > since and (not system or e["system"] == system)]
        if out:
            before = copy.deepcopy(_state)
            _state["positions"][scope] = out[-1]["seq"]
            _commit(before)
    return out


def add_correction(agent: str, system: str, kind: str, component: str, description: str, evidence: str, now: float = None) -> dict:
    item = {"id": secrets.token_hex(4), "at": time.time() if now is None else now, "agent": agent, "system": system,
            "kind": kind, "component": component, "description": description, "evidence": evidence}
    with _lock:
        _load()
        before = copy.deepcopy(_state)
        _state["corrections"].append(item)
        _commit(before)
    return item


def corrections() -> list:
    with _lock:
        _load()
        return list(_state["corrections"])
