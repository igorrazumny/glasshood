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


@dataclass
class Actual:
    """What Azure shows right now, read fresh at every step."""
    ingress_restricted: bool
    revision_active: bool
    replicas: int
    healthy: bool                      # /api/health 200 within 3 s (only meaningful when open)
    queue_generations: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class Step:
    kind: str                          # see STEP_KINDS
    detail: dict = field(default_factory=dict)


STEP_KINDS = (
    "activate_revision", "put_message", "open_ingress", "delete_older_messages",
    "restrict_ingress", "delete_messages_upto", "mark_cleared", "deactivate_revision",
    "wait", "fail_wake", "done",
)


# ---- intent changes (endpoints and the idle timer) -------------------------------------

def wake(intent: Intent, now: float, reason: str) -> Intent:
    """A wake request. Starting from a completed sleep it begins a new wake (new wake_id,
    counts as use: someone opened the app). While awake or waking it changes nothing,
    so repeated wakes are one wake. While going to sleep it reverses the sleep and keeps
    the wake_id, so open tabs' use tokens stay valid."""
    if intent.desired == "awake":
        return intent
    fresh = intent.asleep_done
    return replace(
        intent, desired="awake", generation=intent.generation + 1,
        wake_id=secrets.token_hex(8) if fresh else intent.wake_id,
        last_use=now if fresh else intent.last_use, reason=reason, t0=now,
        queue_cleared_at=0.0, settled=False, asleep_done=False,
    )


def use(intent: Intent, now: float) -> Intent:
    """Person-caused use. Newer use reverses a sleep that has not finished."""
    out = replace(intent, last_use=max(intent.last_use, now))
    if intent.desired == "asleep" and not intent.asleep_done:
        out = replace(out, desired="awake", generation=intent.generation + 1,
                      reason="use_during_sleep", t0=now, queue_cleared_at=0.0, settled=False)
    return out


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
    if not a.revision_active:
        return Step("activate_revision")
    if g not in a.queue_generations:
        return Step("put_message", {"generation": g})
    if a.ingress_restricted:
        return Step("open_ingress")
    if any(x < g for x in a.queue_generations):
        return Step("delete_older_messages", {"generation": g})
    if a.replicas >= 1 and a.healthy:
        return Step("done")
    if not intent.settled and now - intent.t0 >= WAKE_DEADLINE_SECONDS:
        return Step("fail_wake")
    return Step("wait", {"for": "healthy"})


def _toward_asleep(intent: Intent, a: Actual, now: float) -> Step:
    g = intent.generation
    if not a.ingress_restricted:
        return Step("restrict_ingress")
    if any(x <= g for x in a.queue_generations):
        return Step("delete_messages_upto", {"generation": g})
    if not intent.queue_cleared_at:
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
