# File: controller/wake/reconciler.py
# Purpose: REQ-GHA-018 — the only code that changes Azure. One run: take the lease,
# bump the epoch, finish or wait out any operation a previous owner left pending,
# then repeatedly read the newest intent and the actual state and take one step,
# until the state matches, the lease is lost, or the run's time is up.

from __future__ import annotations

import time
from dataclasses import replace
from typing import Callable

from . import core
from .state import Conflict, control_of, entity_of, intent_of

LEASE_SECONDS = 60
MIN_LEASE_LEFT = 45          # issue an ARM request only with this much lease left
RUN_SECONDS = 9 * 60
POLL_SECONDS = 5


class LeaseLost(Exception):
    pass


class Reconciler:
    def __init__(self, store, ops, lease, clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep, notify=None):
        self.store, self.ops, self.lease = store, ops, lease
        self.clock, self.sleep = clock, sleep
        self.notify = notify or (lambda kind, detail: None)
        self.epoch = None

    # ---- ownership ----
    def _renew(self) -> None:
        if not self.lease.renew():
            raise LeaseLost()
        entity, _ = self.store.read()
        if control_of(entity)["epoch"] != self.epoch:
            raise LeaseLost()

    def _write_control(self, change) -> None:
        """Write control fields, conditional on still owning the epoch."""
        while True:
            entity, etag = self.store.read()
            control = control_of(entity)
            if control["epoch"] != self.epoch:
                raise LeaseLost()
            try:
                self.store.write(entity_of(intent_of(entity), change(control)), etag)
                return
            except Conflict:
                continue

    def _take(self) -> bool:
        if not self.lease.acquire(LEASE_SECONDS):
            return False
        while True:
            entity, etag = self.store.read()
            control = control_of(entity)
            control = {**control, "epoch": control["epoch"] + 1}
            try:
                self.store.write(entity_of(intent_of(entity), control), etag)
                self.epoch = control["epoch"]
                return True
            except Conflict:
                continue

    # ---- one ARM operation, recorded before it is sent ----
    def _arm(self, kind: str, send) -> None:
        if self.lease.seconds_left() < MIN_LEASE_LEFT:
            self._renew()
        self._write_control(lambda c: {**c, "op": {"kind": kind, "state": "submitting",
                                                   "issued_at": self.clock(), "epoch": self.epoch}})
        handle = send()
        self._write_control(lambda c: {**c, "op": {**c["op"], "state": "accepted", "url": handle.url}})
        self._await_op({"kind": kind, "state": "accepted", "url": handle.url, "issued_at": self.clock()})

    def _await_op(self, op: dict) -> None:
        """Wait for an operation to be terminal. One still running past its planned time
        is slow, not an outage: it stays tracked and nothing conflicting is sent."""
        slow_reported = False
        while True:
            self._renew()
            if op.get("state") == "accepted" and op.get("url"):
                state = self.ops.op_status(op["url"])
            elif op.get("state") == "accepted":
                state = "Succeeded"               # ARM finished it synchronously
            else:                                  # "submitting": outcome unknown
                state = self.ops.provisioning_state()
                state = "InProgress" if state == "InProgress" else "Succeeded"
            if state != "InProgress":
                if state != "Succeeded":
                    self.store.record("operation_failed", {"op": op, "state": state})
                self._write_control(lambda c: {**c, "op": None})
                return
            if not slow_reported and self.clock() - op.get("issued_at", self.clock()) > 120:
                self.store.record("slow_operation", {"op": op})
                slow_reported = True
            self.sleep(POLL_SECONDS)

    # ---- the run ----
    def run(self) -> str:
        if not self._take():
            return "busy"
        started = self.clock()
        try:
            entity, _ = self.store.read()
            pending = control_of(entity)["op"]
            if pending:
                self.store.record("takeover_pending_op", {"op": pending})
                self._await_op(pending)
            while self.clock() - started < RUN_SECONDS:
                self._renew()
                outcome = self._one_step()
                if outcome in ("done", "wait"):
                    if outcome == "done":
                        return "done"
                    self.sleep(POLL_SECONDS)
            return "timeout"
        except LeaseLost:
            return "lease_lost"
        finally:
            self.lease.release()

    def _idle_check(self, now: float) -> None:
        from .state import update_intent
        update_intent(self.store, lambda i: core.sleep(i, now, "idle") if core.idle_due(i, now) else i)

    def _one_step(self) -> str:
        now = self.clock()
        self._idle_check(now)
        entity, _ = self.store.read()
        intent = intent_of(entity)
        actual, revision = self.ops.read_actual()
        step = core.next_step(intent, actual, now)
        g = intent.generation

        if step.kind == "done":
            self._settle(intent, actual)
            return "done"
        if step.kind == "wait":
            return "wait"
        if intent.settled:
            self.store.record("divergence", {"intent": intent.desired, "generation": g,
                                             "step": step.kind})
            self._mark(g, settled=False)

        if step.kind == "activate_revision":
            self._arm("activate", lambda: self.ops.set_revision_active(revision, True))
        elif step.kind == "deactivate_revision":
            self._arm("deactivate", lambda: self.ops.set_revision_active(revision, False))
        elif step.kind == "open_ingress":
            self._arm("open_ingress", lambda: self.ops.set_restricted(False))
        elif step.kind == "restrict_ingress":
            self._arm("restrict_ingress", lambda: self.ops.set_restricted(True))
        elif step.kind == "put_message":
            self.ops.put_message(g)
        elif step.kind == "delete_older_messages":
            kept = {"current": False}

            def older_or_duplicate(x: int) -> bool:
                if x == g and not kept["current"]:
                    kept["current"] = True
                    return False
                return x <= g
            self.ops.scan_and_delete(older_or_duplicate)
        elif step.kind == "delete_messages_upto":
            self.ops.scan_and_delete(lambda x: x <= g)
        elif step.kind == "mark_cleared":
            self._mark(g, queue_cleared_at=self.clock())
        elif step.kind == "fail_wake":
            from .state import update_intent
            self.store.record("wake_failed", {"generation": g, "t0": intent.t0})
            self.notify("wake_failed", {"generation": g})
            update_intent(self.store, lambda i: core.sleep(i, self.clock(), "wake_failed")
                          if i.generation == g else i)
        return "step"

    def _mark(self, generation: int, **changes) -> None:
        """Change transition fields of the intent, only if it is still that generation."""
        from .state import update_intent
        update_intent(self.store, lambda i: replace(i, **changes) if i.generation == generation else i)

    def _settle(self, intent: core.Intent, actual: core.Actual) -> None:
        if intent.settled and (intent.desired == "awake" or intent.asleep_done):
            return
        changes = {"settled": True}
        if intent.desired == "asleep":
            changes["asleep_done"] = True
        self._mark(intent.generation, **changes)
        self.store.record("settled", {"state": intent.desired, "generation": intent.generation,
                                      "seconds": round(self.clock() - intent.t0, 1)})
