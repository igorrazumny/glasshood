# File: controller/wake/core.py
# Purpose: REQ-GHA-018 wake controller — the pure decisions. No Azure calls here:
# given the newest intent and the actual state read from Azure, say what the one
# next step is. The reconciler (reconciler.py) carries steps out, one at a time,
# re-reading intent and actual state after each.

from __future__ import annotations

import secrets
from dataclasses import dataclass, field, replace

IDLE_SECONDS = 2 * 3600          # clause 7: 2 hours without use
WAKE_DEADLINE_SECONDS = 180      # clause 6: in the app within 3 minutes, else failure
DRAIN_SECONDS = 160              # cooldown 30 s + grace 120 s + 10 s margin (design v6)
SCAN_VISIBILITY = 30             # a scanned message is invisible this long (design v6)
SCAN_FRESH_SECONDS = 15          # a queue scan older than this is scanned again
EMPTY_TRUST_SECONDS = 120        # clean empty scans this long outweigh the approximate count


@dataclass
class Intent:
    """The single state entity's intent fields. Endpoints change these and nothing else."""
    desired: str = "asleep"            # "awake" | "asleep"
    generation: int = 0                # rises on every change of intent
    wake_id: str = ""                  # new each time a wake starts from a completed sleep
    last_use: float = 0.0
    hold_until: float = 0.0
    reason: str = ""                   # why the newest intent was set
    t0: float = 0.0                    # when the newest intent's transition started
    queue_cleared_at: float = 0.0      # D in design v6 (asleep only)
    settled: bool = True               # actual state matched intent at the last check
    asleep_done: bool = True           # the last sleep reached zero replicas
    deadline: float = 0.0              # awake: the wake fails if not awake by then


@dataclass
class QueueView:
    """What one fresh-receipt scan of the wake queue left behind (design v6). Peek is
    never used to decide: it shows only visible messages, at most 32."""
    desired: str                       # the intent the scan decided for
    generation: int
    at: float                          # when the scan ran
    current: int = 0                   # generation-G messages left (awake keeps one)
    older: int = 0                     # messages < G left (awake keeps one until G is seen)
    newer: int = 0                     # messages > G: a later intent not recorded yet
    clean: bool = True                 # saw every visible message, every receipt worked
    approx: int = 0                    # approximate count afterwards, invisible ones too
    empty_since: float = 0.0           # asleep: clean scans have found nothing since then

    def fresh_for(self, intent: "Intent", now: float) -> bool:
        return (self.desired == intent.desired and self.generation == intent.generation
                and now - self.at <= SCAN_FRESH_SECONDS)


@dataclass
class Actual:
    """What Azure shows right now, read fresh at every step."""
    ingress_restricted: bool
    revision_active: bool
    replicas: int
    healthy: bool                      # /api/health 200 within 3 s (only meaningful when open)
    queue: QueueView | None = None     # the reconciler's latest scan, if any


@dataclass(frozen=True)
class Step:
    kind: str                          # see STEP_KINDS
    detail: dict = field(default_factory=dict)


STEP_KINDS = (
    "activate_revision", "scan_queue", "put_message", "open_ingress",
    "restrict_ingress", "mark_cleared", "deactivate_revision",
    "wait", "fail_wake", "done",
)


# ---- intent changes (endpoints and the idle timer) -------------------------------------

def wake(intent: Intent, now: float, reason: str) -> Intent:
    """A wake request (a verified visit, or the operator). While awake or waking it
    changes nothing, so repeated wakes are one wake and renewing a token is not use.
    Otherwise it is a visit, so it counts as use: from a completed sleep it begins a
    new wake (new wake_id); while going to sleep it reverses the sleep and keeps the
    wake_id, so open tabs' use tokens stay valid. Either way the idle timer restarts,
    so the idle check cannot turn the reversal straight back into a sleep."""
    if intent.desired == "awake":
        return intent
    fresh = intent.asleep_done
    return replace(
        intent, desired="awake", generation=intent.generation + 1,
        wake_id=secrets.token_hex(8) if fresh else intent.wake_id,
        last_use=max(intent.last_use, now), reason=reason, t0=now,
        deadline=now + WAKE_DEADLINE_SECONDS,
        queue_cleared_at=0.0, settled=False, asleep_done=False,
    )


def use(intent: Intent, now: float) -> Intent:
    """Person-caused use. Newer use reverses a sleep that has not finished."""
    out = replace(intent, last_use=max(intent.last_use, now))
    if intent.desired == "asleep" and not intent.asleep_done:
        out = replace(out, desired="awake", generation=intent.generation + 1,
                      reason="use_during_sleep", t0=now, deadline=now + WAKE_DEADLINE_SECONDS,
                      queue_cleared_at=0.0, settled=False)
    return out


def extend_deadline(intent: Intent, now: float) -> Intent:
    """A wake that waited on a genuinely slow Azure operation, or a settled wake found
    diverged, gets a full wake time from now (amendment 2: it finishes after that
    operation does). Failed or refused operations never extend it."""
    if intent.desired != "awake":
        return intent
    return replace(intent, deadline=max(intent.deadline, now + WAKE_DEADLINE_SECONDS))


def sleep(intent: Intent, now: float, reason: str) -> Intent:
    """A sleep request (operator, idle timer, failed wake). Ends any hold."""
    if intent.desired == "asleep":
        return replace(intent, hold_until=0.0)
    return replace(intent, desired="asleep", generation=intent.generation + 1,
                   hold_until=0.0, reason=reason, t0=now, queue_cleared_at=0.0,
                   settled=False, asleep_done=False)


def hold(intent: Intent, now: float, seconds: int) -> Intent:
    """Keep the app awake for a set time; wakes it if needed."""
    out = wake(intent, now, "hold") if intent.desired != "awake" else intent
    return replace(out, hold_until=max(out.hold_until, now + seconds))


def idle_due(intent: Intent, now: float) -> bool:
    """Clause 7: 2 hours without use and no hold."""
    return (intent.desired == "awake" and now - intent.last_use >= IDLE_SECONDS
            and now >= intent.hold_until)


# ---- the next step ------------------------------------------------------------------------

def next_step(intent: Intent, actual: Actual, now: float) -> Step:
    if intent.desired == "awake":
        return _toward_awake(intent, actual, now)
    return _toward_asleep(intent, actual, now)


def _toward_awake(intent: Intent, a: Actual, now: float) -> Step:
    g = intent.generation
    # The wake's whole budget, checked before every step: a step that keeps failing
    # ends the wake at its deadline instead of being retried for ever.
    if not intent.settled and now >= (intent.deadline or intent.t0 + WAKE_DEADLINE_SECONDS):
        return Step("fail_wake")
    if not a.revision_active:
        return Step("activate_revision")
    q = a.queue
    if q is None or not q.fresh_for(intent, now):
        return Step("scan_queue")
    if q.current == 0:
        # Put only after a complete scan found none; otherwise scan the rest first.
        return Step("put_message", {"generation": g}) if q.clean else Step("scan_queue")
    if a.ingress_restricted:
        return Step("open_ingress")
    if q.older or not q.clean:
        return Step("scan_queue")              # the same scan that sees G deletes the older
    if a.replicas >= 1 and a.healthy:
        return Step("done")
    return Step("wait", {"for": "healthy"})


def queue_plan(desired: str, g: int, gens: list[int]) -> list[bool]:
    """For one scan's messages (their generations, in the order received), which to
    delete (True) and which to keep (False), decided for intent (desired, g):
      asleep: delete everything <= G; a newer message belongs to a later intent.
      awake:  keep exactly one generation-G message and delete older ones only once
              that message is seen in this same scan. With none seen, keep the newest
              older message so the app stays up until G is put, and delete the rest.
              Newer messages are kept."""
    if desired == "asleep":
        return [x <= g for x in gens]
    if g in gens:
        keep = gens.index(g)
    else:
        older = [i for i, x in enumerate(gens) if x < g]
        keep = max(older, key=lambda i: gens[i]) if older else None
    return [i != keep and x <= g for i, x in enumerate(gens)]


def queue_empty(q: QueueView, now: float) -> bool:
    """Asleep: the queue holds nothing at all, invisible messages included. A scan
    sees only visible messages, so it takes clean scans that found nothing for longer
    than one visibility timeout: any message a crashed or competing scan left
    invisible has reappeared by then. The approximate count (invisible ones too) must
    also be zero, unless clean scans have kept finding nothing for 2 minutes."""
    if q.current or q.older or q.newer or not q.clean or not q.empty_since:
        return False
    window = now - q.empty_since
    return window > SCAN_VISIBILITY + 5 and (q.approx == 0 or window > EMPTY_TRUST_SECONDS)


def _toward_asleep(intent: Intent, a: Actual, now: float) -> Step:
    if not a.ingress_restricted:
        return Step("restrict_ingress")
    q = a.queue
    if not intent.queue_cleared_at:
        if q is None or not q.fresh_for(intent, now) or q.current or q.older or not q.clean:
            return Step("scan_queue")
        if not queue_empty(q, now):
            return Step("wait", {"for": "queue"})  # newer, or invisible messages to reappear
        return Step("mark_cleared")            # D: the drain is measured from here
    if a.replicas == 0:
        return Step("done")
    # An unhealthy wake never served anyone: no drain. Otherwise wait out the drain,
    # measured from when the queue was actually emptied, never cutting it short.
    if intent.reason == "wake_failed":
        return Step("deactivate_revision") if a.revision_active else Step("wait", {"for": "zero"})
    if now - intent.queue_cleared_at >= DRAIN_SECONDS and a.revision_active:
        return Step("deactivate_revision")
    return Step("wait", {"for": "drain"})


def status(intent: Intent) -> str:
    """The four-state contract for the public pages and the waking page. Read from the
    state entity only: answering it never touches the app or Azure (clause 1)."""
    if intent.desired == "awake":
        return "awake" if intent.settled else "waking"
    return "asleep" if intent.asleep_done else "going-to-sleep"
