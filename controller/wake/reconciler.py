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
from .state import Conflict, control_of, entity_of, intent_of, update_intent

LEASE_SECONDS = 60
MIN_LEASE_LEFT = 45          # issue an ARM request only with this much lease left
RUN_SECONDS = 9 * 60
POLL_SECONDS = 5
SLOW_SECONDS = 120           # an operation still pending after this is recorded as slow
TERMINAL = ("Succeeded", "Failed", "Canceled")   # every other ARM status is still pending


class LeaseLost(Exception):
    pass


class RunOver(Exception):
    """The run's time is up; a pending operation stays recorded for the next run."""


class Reconciler:
    def __init__(self, store, ops, lease, clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep, notify=None):
        self.store, self.ops, self.lease = store, ops, lease
        self.clock, self.sleep = clock, sleep
        self.notify = notify or (lambda kind, detail: None)
        self.epoch = None
        self.started = None
        self.queue_view = None       # the latest queue scan in this run
        self._step_generation = None # the intent generation the current step serves
        self._reported = set()       # failure kinds already reported in this run

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
                                                   "issued_at": self.clock(), "epoch": self.epoch,
                                                   "generation": self._step_generation}})
        handle = send()
        self._write_control(lambda c: {**c, "op": {**c["op"], "state": "accepted", "url": handle.url}})
        self._await_op({"kind": kind, "state": "accepted", "url": handle.url, "issued_at": self.clock(),
                        "generation": self._step_generation})

    def _await_op(self, op: dict) -> None:
        """Wait until an operation is terminal (Succeeded, Failed or Canceled; anything
        else is still pending). One still running past its planned time is slow, not an
        outage: it stays tracked, nothing conflicting is sent, and a wake waiting on it
        gets its full time again once it finishes."""
        slow = False
        while True:
            self._renew()
            if op.get("state") == "accepted" and op.get("url"):
                state = self.ops.op_status(op["url"])
            elif op.get("state") == "accepted":
                state = "Succeeded"               # ARM finished it synchronously
            else:
                # "submitting": whether it reached ARM is unknown, so wait until the
                # resource itself is no longer changing.
                state = self.ops.provisioning_state()
            if state in TERMINAL:
                if state != "Succeeded":
                    self.store.record("operation_failed", {"op": op, "state": state})
                    self._report("operation_failed", {"op": op.get("kind"), "state": state})
                    now = self.clock()
                    gen = op.get("generation")
                    update_intent(self.store, lambda i: core.refused(i, op.get("kind", ""), now)
                                  if gen is None or i.generation == gen else i)
                self._write_control(lambda c: {**c, "op": None})
                if slow and state == "Succeeded":
                    now = self.clock()
                    update_intent(self.store, lambda i: core.extend_deadline(i, now))
                return
            if not slow and self.clock() - op.get("issued_at", self.clock()) > SLOW_SECONDS:
                self.store.record("slow_operation", {"op": op, "state": state})
                slow = True
            if self.started is not None and self.clock() - self.started >= RUN_SECONDS:
                raise RunOver()
            self.sleep(POLL_SECONDS)

    def _report(self, kind: str, detail: dict) -> None:
        if kind not in self._reported:
            self._reported.add(kind)
            self.notify(kind, detail)

    # ---- the run ----
    def run(self) -> str:
        if not self._take():
            return "busy"
        started = self.started = self.clock()
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
        except RunOver:
            return "timeout"
        except LeaseLost:
            return "lease_lost"
        finally:
            self.lease.release()

    def _idle_check(self, now: float) -> None:
        update_intent(self.store, lambda i: core.sleep(i, now, "idle") if core.idle_due(i, now) else i)

    def _one_step(self) -> str:
        now = self.clock()
        self._idle_check(now)
        entity, _ = self.store.read()
        intent = intent_of(entity)
        actual, revision = self.ops.read_actual()
        actual.queue = self.queue_view
        step = core.next_step(intent, actual, now)
        g = self._step_generation = intent.generation

        if step.kind == "done":
            self._settle(intent, actual)
            return "done"
        if step.kind == "wait":
            return "wait"
        if intent.settled and step.kind != "scan_queue":
            self.store.record("divergence", {"intent": intent.desired, "generation": g,
                                             "step": step.kind})
            self._mark(g, settled=False)
            update_intent(self.store, lambda i: core.extend_deadline(i, now) if i.generation == g else i)

        if step.kind == "activate_revision":
            self._arm("activate", lambda: self.ops.set_revision_active(revision, True))
        elif step.kind == "deactivate_revision":
            self._arm("deactivate", lambda: self.ops.set_revision_active(revision, False))
        elif step.kind == "open_ingress":
            self._arm("open_ingress", lambda: self.ops.set_restricted(False))
        elif step.kind == "restrict_ingress":
            self._arm("restrict_ingress", lambda: self.ops.set_restricted(True))
        elif step.kind == "scan_queue":
            self._scan()
        elif step.kind == "put_message":
            self.ops.put_message(g)
            self.queue_view = None
        elif step.kind == "mark_cleared":
            self._mark(g, queue_cleared_at=self.clock())
        elif step.kind == "fail_wake":
            self.store.record("wake_failed", {"generation": g, "t0": intent.t0})
            self._report("wake_failed", {"generation": g})
            update_intent(self.store, lambda i: core.sleep(i, self.clock(), "wake_failed")
                          if i.generation == g else i)
        return "step"

    def _scan(self) -> None:
        def read_intent():
            i = intent_of(self.store.read()[0])
            return i.desired, i.generation
        before = self.queue_view
        view = self.ops.scan_queue(read_intent, self.clock())
        nothing = view.clean and not (view.current or view.older or view.newer)
        if nothing:
            same = (before is not None and before.desired == view.desired
                    and before.generation == view.generation and before.empty_since)
            view.empty_since = before.empty_since if same else view.at
        if view.newer:
            self.store.record("newer_message", {"intent": view.desired, "generation": view.generation,
                                                "newer": view.newer})
        self.queue_view = view

    def _mark(self, generation: int, **changes) -> None:
        """Change transition fields of the intent, only if it is still that generation."""
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
