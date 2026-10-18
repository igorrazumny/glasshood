# File: controller/wake/api.py
# Purpose: REQ-GHA-018 — the controller's HTTP endpoints as plain functions. They
# only record intent (and ask the reconciler to run); they never touch Azure.

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from . import core, recaptcha, tokens
from .state import intent_of, update_intent

WAKING_EXPECTED_SECONDS = 60
MAX_HOLD_HOURS = 72


@dataclass
class Config:
    token_secret: bytes
    recaptcha_secret: str
    allowed_origins: set[str]          # https://app.glasshood.ai, its SWA address, ...
    recaptcha_hosts: set[str]          # hostnames reCAPTCHA must report
    always_on: bool = False            # before the cutover the app runs all the time


@dataclass
class Reply:
    status: int
    body: dict | None = None


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if ts else ""


class Api:
    def __init__(self, store, cfg: Config, kick: Callable[[], None],
                 verify: Callable[[str], bool] | None = None, clock=time.time):
        self.store, self.cfg, self.kick, self.clock = store, cfg, kick, clock
        self._verify = verify or (lambda t: recaptcha.verify(cfg.recaptcha_secret, t, cfg.recaptcha_hosts))

    def _intent(self) -> core.Intent:
        entity, _ = self.store.read()
        return intent_of(entity)

    def _token_ok(self, intent: core.Intent, token: str) -> bool:
        return (not intent.asleep_done) and tokens.valid(
            self.cfg.token_secret, token or "", intent.wake_id, self.clock())

    def _origin_ok(self, origin: str | None) -> bool:
        return origin in self.cfg.allowed_origins

    # GET /status — public, read from the state entity only
    def status(self) -> Reply:
        i = self._intent()
        s = "awake" if self.cfg.always_on else core.status(i)
        return Reply(200, {"state": s, "since": _iso(i.t0),
                           "expected_seconds": WAKING_EXPECTED_SECONDS if s == "waking" else 0})

    # POST /wake — public; needs a verified reCAPTCHA token, or the current wake's use token
    def wake(self, body: dict, origin: str | None) -> Reply:
        if not self._origin_ok(origin):
            return Reply(403, {"error": "origin"})
        current = self._intent()
        by_token = self._token_ok(current, body.get("use_token", ""))
        if not by_token and not self._verify(body.get("recaptcha_token", "")):
            return Reply(403, {"error": "not verified"})
        now = self.clock()
        after = update_intent(self.store, lambda i: core.wake(i, now, "visit"))
        if after.generation != current.generation:
            self.kick()
        return Reply(202, tokens.issue(self.cfg.token_secret, after.wake_id, now))

    # POST /use — public; person-caused use, needs the current wake's use token
    def use(self, body: dict, origin: str | None) -> Reply:
        if not self._origin_ok(origin):
            return Reply(403, {"error": "origin"})
        current = self._intent()
        if not self._token_ok(current, body.get("use_token", "")):
            return Reply(403, {"error": "token"})
        now = self.clock()
        after = update_intent(self.store, lambda i: core.use(i, now))
        if after.desired != current.desired:
            self.kick()
        return Reply(204)

    # Operator endpoints (function key)
    def sleep(self) -> Reply:
        now = self.clock()
        update_intent(self.store, lambda i: core.sleep(i, now, "operator"))
        self.kick()
        return Reply(202, self.status().body)

    def operator_wake(self) -> Reply:
        now = self.clock()
        update_intent(self.store, lambda i: core.wake(i, now, "operator"))
        self.kick()
        return Reply(202, self.status().body)

    def hold(self, hours: float) -> Reply:
        if not 0 < hours <= MAX_HOLD_HOURS:
            return Reply(400, {"error": f"hours must be in (0, {MAX_HOLD_HOURS}]"})
        now = self.clock()
        after = update_intent(self.store, lambda i: core.hold(i, now, int(hours * 3600)))
        self.kick()
        return Reply(202, {**self.status().body, "hold_until": _iso(after.hold_until)})

    def operator_status(self) -> Reply:
        i = self._intent()
        events = self.store.recent_events() if hasattr(self.store, "recent_events") else []
        return Reply(200, {**self.status().body, "desired": i.desired, "generation": i.generation,
                           "last_use": _iso(i.last_use), "hold_until": _iso(i.hold_until),
                           "reason": i.reason, "events": events})
