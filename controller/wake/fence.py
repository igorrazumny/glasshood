# File: controller/wake/fence.py
# Purpose: REQ-GHA-018 clause 13 — the rollback's hold on the controller.
#   pin()    the rollback. One conditional write makes the intent awake and pinned
#            (never put to sleep, no idle, no failed-wake sleep) and bumps the epoch, so a
#            running reconciler fails its next ownership check. A sender already past
#            that check (or a request already with Azure) can still land one late
#            change; there is no ETag to refuse it. The reconciler stays on and
#            repairs it like any divergence, within a minute's run (clause 11).
#   unpin()  the cutover's enable: the app may sleep again, idle counted from now.
#   halt()   last resort for a controller that itself misbehaves: no reconciler takes
#            over or sends anything, so nothing repairs a late change either. Check
#            the app again after 5 minutes.
#   wait_pending()  waits out the one operation that may be with Azure.

from __future__ import annotations

import time

from .reconciler import TERMINAL
from .state import Conflict, control_of, entity_of, intent_of

SUBMIT_SETTLE_SECONDS = 35      # a "submitting" request reaches ARM within its 30 s timeout


def _set(store, change) -> dict:
    while True:
        entity, etag = store.read()
        control = change(control_of(entity))
        try:
            store.write(entity_of(intent_of(entity), control), etag)
            return control
        except Conflict:
            continue


def _pin_write(store, change_intent, change_control) -> None:
    while True:
        entity, etag = store.read()
        try:
            store.write(entity_of(change_intent(intent_of(entity)), change_control(control_of(entity))), etag)
            return
        except Conflict:
            continue


def pin(store, now: float) -> None:
    from dataclasses import replace
    from . import core
    _pin_write(store,
               lambda i: replace(core.wake(i, now, "rollback"), pinned=True),
               lambda c: {**c, "halted": False, "epoch": c["epoch"] + 1})


def unpin(store, now: float) -> None:
    from dataclasses import replace
    _pin_write(store,
               lambda i: replace(i, pinned=False, last_use=max(i.last_use, now)),
               lambda c: c)


def halt(store) -> dict:
    return _set(store, lambda c: {**c, "halted": True, "epoch": c["epoch"] + 1})


def resume(store) -> dict:
    return _set(store, lambda c: {**c, "halted": False})


def wait_pending(store, ops, clock=time.time, sleep=time.sleep, limit_seconds=900) -> dict | None:
    """After halt(): wait until the recorded operation, if any, is terminal, then clear
    it. Returns the operation waited for. Raises TimeoutError past limit_seconds."""
    op = control_of(store.read()[0])["op"]
    if not op:
        return None
    started = clock()
    while True:
        if op.get("state") == "accepted" and op.get("url"):
            state = ops.op_status(op["url"])
        elif op.get("state") == "accepted":
            state = "Succeeded"
        elif clock() < op.get("issued_at", 0) + SUBMIT_SETTLE_SECONDS:
            state = "pending"
        else:
            state = ops.provisioning_state()
        if state in TERMINAL:
            _set(store, lambda c: {**c, "op": None})
            return {**op, "final": state}
        if clock() - started > limit_seconds:
            raise TimeoutError(f"operation still pending: {op}")
        sleep(5)
