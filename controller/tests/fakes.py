# File: controller/tests/fakes.py
# Purpose: In-memory stand-ins for Table storage, the lease, the queue and ARM, so
# the controller's ordering, takeover and timing can be tested without Azure.

from __future__ import annotations

import copy
import itertools
import json
from types import SimpleNamespace

from azure.core.exceptions import ResourceNotFoundError

from wake.azure_ops import AzureOps, OpHandle
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


class FakeQueue:
    """The Storage queue calls AzureOps uses, with visibility and pop receipts: a
    received message is invisible for its visibility timeout and only its newest
    receipt works; a stale receipt gets 404, as in Azure."""

    def __init__(self, clock: Clock):
        self.clock = clock
        self.msgs = {}                    # id -> {"g", "content", "visible_at", "receipt"}
        self._ids = itertools.count()
        self._receipts = itertools.count()
        self.after_receive = None         # hook(batch) between receive and decisions

    def send_message(self, content, time_to_live=None):
        i = next(self._ids)
        self.msgs[i] = {"content": content, "visible_at": 0.0, "receipt": None}

    def receive_messages(self, messages_per_page=32, max_messages=32, visibility_timeout=30):
        self.clock.sleep(0.1)                     # a Storage call takes time
        now = self.clock()
        out = []
        for i, m in sorted(self.msgs.items()):
            if len(out) >= max_messages:
                break
            if m["visible_at"] <= now:
                m["receipt"] = f"r{next(self._receipts)}"
                m["visible_at"] = now + visibility_timeout
                out.append(SimpleNamespace(id=i, pop_receipt=m["receipt"], content=m["content"]))
        if self.after_receive:
            self.after_receive(out)
        return out

    def _check(self, i, receipt):
        if i not in self.msgs or self.msgs[i]["receipt"] != receipt:
            raise ResourceNotFoundError("receipt")

    def delete_message(self, i, receipt):
        self._check(i, receipt)
        del self.msgs[i]

    def update_message(self, i, receipt, visibility_timeout=0):
        self._check(i, receipt)
        self.msgs[i]["receipt"] = f"r{next(self._receipts)}"
        self.msgs[i]["visible_at"] = self.clock() + visibility_timeout

    def get_queue_properties(self):
        return SimpleNamespace(approximate_message_count=len(self.msgs))

    def generations(self):
        return [(i, json.loads(m["content"])["generation"]) for i, m in sorted(self.msgs.items())]


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
        self._queue = FakeQueue(clock)
        self.ops = {}                                # url -> (done_at, apply)
        self._want_since = None
        self._empty_since = None
        self.arm_calls = []
        self.history = []                            # (time, "restricted"|"open"|"zero")
        self.pending_states = ["InProgress"]        # statuses ARM reports while pending
        self.fail = {}                               # op name -> terminal status to end with
        clock.hooks.append(self._tick)

    @property
    def queue(self):
        """(id, generation) of every message, invisible ones too."""
        return self._queue.generations()

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
        self.clock.sleep(1)                          # an ARM request takes time
        url = f"op/{name}/{len(self.ops)}"
        failing = self.fail.get(name)
        self.ops[url] = (self.clock() + self.arm_seconds, (lambda: None) if failing else apply, False)
        self.op_end = getattr(self, "op_end", {})
        self.op_end[url] = failing or "Succeeded"
        self.arm_calls.append(name)
        return OpHandle(url)

    # AzureOps interface
    def op_status(self, url):
        if self.ops[url][2]:
            return self.op_end[url]
        return self.pending_states[len(self.arm_calls) % len(self.pending_states)]

    def provisioning_state(self):
        return self.pending_states[0] if any(not d for _, _, d in self.ops.values()) else "Succeeded"

    def read_actual(self):
        healthy = (not self.restricted) and self.replicas > 0 and self.healthy_app
        return Actual(self.restricted, self.active, self.replicas, healthy), "rev1"

    put_message = AzureOps.put_message
    scan_queue = AzureOps.scan_queue

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

