# File: controller/tests/fakes.py
# Purpose: In-memory stand-ins for Table storage, the lease, the queue and ARM, so
# the controller's ordering, takeover and timing can be tested without Azure.

from __future__ import annotations

import copy
import itertools

from wake.azure_ops import OpHandle
from wake.core import Actual, Intent
from wake.state import Conflict, entity_of


class Clock:
    def __init__(self, t: float = 1_000_000.0):
        self.t = t
        self.hooks = []          # called on every advance, to move fake Azure along

    def __call__(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.t += s
        for h in self.hooks:
            h(self.t)


class MemStore:
    def __init__(self, intent: Intent | None = None):
        self._entity = entity_of(intent or Intent(), {"epoch": 0, "op": None})
        self._etag = 0
        self.events = []

    def read(self):
        return copy.deepcopy(self._entity), str(self._etag)

    def write(self, entity, etag):
        if etag != str(self._etag):
            raise Conflict("etag")
        self._entity = copy.deepcopy(entity)
        self._etag += 1
        return str(self._etag)

    def record(self, kind, detail):
        self.events.append((kind, detail))

    def kinds(self):
        return [k for k, _ in self.events]


class Lease:
    def __init__(self, clock: Clock):
        self.clock, self.until, self.held, self.lose_at = clock, 0.0, False, None

    def acquire(self, seconds):
        if self.held and self.clock() < self.until:
            return False
        self.held, self.until = True, self.clock() + seconds
        return True

    def renew(self):
        if self.lose_at is not None and self.clock() >= self.lose_at:
            self.held = False
            return False
        if not self.held:
            return False
        self.until = self.clock() + 60
        return True

    def seconds_left(self):
        return self.until - self.clock()

    def release(self):
        self.held = False


class FakeAzure:
    """A tiny model of the container app: ARM writes complete after `arm_seconds`;
    a replica starts `start_seconds` after there is a wake message and an active
    revision; with no message it stops after the drain."""

    def __init__(self, clock: Clock, arm_seconds=20, start_seconds=20, drain_seconds=150,
                 healthy_app=True):
        self.clock = clock
        self.arm_seconds, self.start_seconds, self.drain_seconds = arm_seconds, start_seconds, drain_seconds
        self.healthy_app = healthy_app
        self.restricted, self.active, self.replicas = True, True, 0
        self.queue = []                              # list of (id, generation)
        self._ids = itertools.count()
        self.ops = {}                                # url -> (done_at, apply)
        self._want_since = None
        self._empty_since = None
        self.arm_calls = []
        self.history = []                            # (time, "restricted"|"open"|"zero")
        clock.hooks.append(self._tick)

    # model time
    def _tick(self, now):
        for url, (done_at, apply, done) in list(self.ops.items()):
            if not done and now >= done_at:
                apply()
                self.ops[url] = (done_at, apply, True)
        want = self.active and bool(self.queue)
        if want:
            self._empty_since = None
            self._want_since = self._want_since or now
            if self.replicas == 0 and now - self._want_since >= self.start_seconds:
                self.replicas = 1
        else:
            self._want_since = None
            if not self.active:
                self.replicas = 0
            elif self.replicas:
                self._empty_since = self._empty_since or now
                if now - self._empty_since >= self.drain_seconds:
                    self.replicas = 0

    def _async(self, name, apply):
        url = f"op/{name}/{len(self.ops)}"
        self.ops[url] = (self.clock() + self.arm_seconds, apply, False)
        self.arm_calls.append(name)
        return OpHandle(url)

    # AzureOps interface
    def op_status(self, url):
        return "Succeeded" if self.ops[url][2] else "InProgress"

    def provisioning_state(self):
        return "InProgress" if any(not d for _, _, d in self.ops.values()) else "Succeeded"

    def read_actual(self):
        healthy = (not self.restricted) and self.replicas > 0 and self.healthy_app
        return Actual(self.restricted, self.active, self.replicas, healthy,
                      [g for _, g in self.queue]), "rev1"

    def peek_generations(self):
        return [g for _, g in self.queue]

    def set_restricted(self, restricted):
        def apply():
            self.restricted = restricted
            self.history.append((self.clock(), "restricted" if restricted else "open"))
        return self._async("restrict" if restricted else "open", apply)

    def set_revision_active(self, revision, active):
        def apply():
            self.active = active
            self.history.append((self.clock(), "activated" if active else "deactivated"))
            if not active:
                self.replicas = 0
        return self._async("activate" if active else "deactivate", apply)

    def put_message(self, generation):
        self.queue.append((next(self._ids), generation))

    def scan_and_delete(self, should_delete):
        n = 0
        for item in list(self.queue):
            if should_delete(item[1]):
                self.queue.remove(item)
                n += 1
        return n
