# File: controller/wake/fence.py
# Purpose: REQ-GHA-018 clause 13 — stopping the reconciler for a rollback, so that no
# change of its can land after the rollback's own. halt() sets `halted` and bumps the
# epoch in one conditional write: a running reconciler fails its next ownership check
# before it can send anything, and no new run may take over. wait_pending() then waits
# out the one operation that may already be with Azure.

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
