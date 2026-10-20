# File: controller/tests/test_controller.py
# Purpose: REQ-GHA-018 wake controller behaviour against in-memory fakes:
# wake, idle sleep, use tokens, failed wake, takeover, lease loss, drain, holds,
# queue hygiene and divergence repair.

from wake import core, tokens
from wake.api import Api, Config
from wake.reconciler import Reconciler
from wake.state import control_of, entity_of, intent_of

from types import SimpleNamespace

from .fakes import Clock, FakeAzure, Lease, MemStore

ORIGIN = "https://app.glasshood.ai"
SECRET = b"k" * 32


def rig(**azure):
    clock = Clock()
    store = MemStore()
    az = FakeAzure(clock, **azure)
    kicks = []
    api = Api(store, Config(SECRET, "rs", {ORIGIN}, {"app.glasshood.ai"}), kick=lambda: kicks.append(1),
              verify=lambda t: t == "good", clock=clock)
    lease = Lease(clock)

    def reconcile():
        return Reconciler(store, az, lease, clock=clock, sleep=clock.sleep).run()
    return clock, store, az, api, reconcile


def intent(store):
    return intent_of(store.read()[0])


def wake_and_settle(clock, store, az, api, reconcile):
    r = api.wake({"recaptcha_token": "good"}, ORIGIN)
    assert r.status == 202
    assert reconcile() == "done"
    return r.body


# ---- wake ----

def test_wake_reaches_awake_within_three_minutes():
    clock, store, az, api, reconcile = rig()
    t0 = clock()
    body = wake_and_settle(clock, store, az, api, reconcile)
    assert api.status().body["state"] == "awake"
    assert clock() - t0 < core.WAKE_DEADLINE_SECONDS
    assert not az.restricted and az.replicas == 1 and [g for _, g in az.queue] == [intent(store).generation]
    assert tokens.valid(SECRET, body["use_token"], intent(store).wake_id, clock())


def test_raw_wake_without_recaptcha_changes_nothing():
    clock, store, az, api, reconcile = rig()
    assert api.wake({}, ORIGIN).status == 403
    assert api.wake({"recaptcha_token": "forged"}, ORIGIN).status == 403
    assert api.wake({"recaptcha_token": "good"}, "https://evil.example").status == 403
    assert intent(store).desired == "asleep"


def test_repeated_wakes_are_one_wake():
    clock, store, az, api, reconcile = rig()
    api.wake({"recaptcha_token": "good"}, ORIGIN)
    g = intent(store).generation
    api.wake({"recaptcha_token": "good"}, ORIGIN)
    assert intent(store).generation == g


def test_wake_renewal_is_not_use():
    clock, store, az, api, reconcile = rig()
    wake_and_settle(clock, store, az, api, reconcile)
    before = intent(store).last_use
    clock.sleep(600)
    assert api.wake({"recaptcha_token": "good"}, ORIGIN).status == 202
    assert intent(store).last_use == before


# ---- use tokens ----

def test_use_needs_the_current_wakes_token():
    clock, store, az, api, reconcile = rig()
    body = wake_and_settle(clock, store, az, api, reconcile)
    assert api.use({"use_token": body["use_token"]}, ORIGIN).status == 204
    assert api.use({}, ORIGIN).status == 403
    other = tokens.issue(SECRET, "someotherwake", clock())
    assert api.use({"use_token": other["use_token"]}, ORIGIN).status == 403
    expired = tokens.issue(SECRET, intent(store).wake_id, clock() - tokens.USE_TOKEN_SECONDS - 1)
    assert api.use({"use_token": expired["use_token"]}, ORIGIN).status == 403


def test_token_from_before_a_completed_sleep_is_refused():
    clock, store, az, api, reconcile = rig()
    body = wake_and_settle(clock, store, az, api, reconcile)
    api.sleep()
    assert reconcile() == "done"
    assert api.use({"use_token": body["use_token"]}, ORIGIN).status == 403


# ---- idle sleep (amended acceptance: going to sleep within 2 min, asleep within 10) ----

def test_idle_sleep_after_two_hours_and_an_idle_tab_does_not_prevent_it():
    clock, store, az, api, reconcile = rig()
    wake_and_settle(clock, store, az, api, reconcile)
    threshold = intent(store).last_use + core.IDLE_SECONDS
    while not intent(store).asleep_done or intent(store).desired == "awake":
        clock.sleep(60)                 # the 1-minute timer, with nobody using the app
        reconcile()
    restricted_at = [t for t, what in az.history if what == "restricted"][-1]
    assert threshold <= restricted_at <= threshold + 120     # going to sleep: nobody new gets in
    assert az.replicas == 0 and api.status().body["state"] == "asleep"
    assert clock() - threshold <= 600


def test_use_resets_the_two_hours():
    clock, store, az, api, reconcile = rig()
    body = wake_and_settle(clock, store, az, api, reconcile)
    clock.sleep(core.IDLE_SECONDS - 60)
    api.use({"use_token": body["use_token"]}, ORIGIN)
    clock.sleep(120)
    reconcile()
    assert intent(store).desired == "awake"


def test_use_during_going_to_sleep_reverses_it():
    clock, store, az, api, reconcile = rig()
    body = wake_and_settle(clock, store, az, api, reconcile)
    api.sleep()
    store_entity = intent(store)
    assert store_entity.desired == "asleep" and not store_entity.asleep_done
    assert api.use({"use_token": body["use_token"]}, ORIGIN).status == 204
    assert intent(store).desired == "awake"
    assert reconcile() == "done"
    assert not az.restricted and az.replicas == 1


def test_hold_prevents_idle_sleep_and_operator_sleep_ends_it():
    clock, store, az, api, reconcile = rig()
    wake_and_settle(clock, store, az, api, reconcile)
    api.hold(4)
    clock.sleep(core.IDLE_SECONDS + 600)
    reconcile()
    assert intent(store).desired == "awake"
    api.sleep()
    assert intent(store).hold_until == 0.0 and intent(store).desired == "asleep"


# ---- drain and forced sleep ----

def test_drain_is_never_cut_short_and_force_only_after_it():
    clock, store, az, api, reconcile = rig(drain_seconds=10_000)   # replica refuses to stop
    wake_and_settle(clock, store, az, api, reconcile)
    api.sleep()
    reconcile()
    i = intent(store)
    assert i.asleep_done and az.replicas == 0
    deactivated_at = [t for t, what in az.history if what == "deactivated"][-1]
    assert deactivated_at >= i.queue_cleared_at + core.DRAIN_SECONDS


def test_slow_operation_is_tracked_not_abandoned_and_nothing_conflicting_is_sent():
    clock, store, az, api, reconcile = rig(arm_seconds=400)
    api.wake({"recaptcha_token": "good"}, ORIGIN)
    reconcile()
    assert "slow_operation" in store.kinds()
    open_done = [t for t, what in az.history if what == "open"]
    assert open_done, "the slow operation was waited out"
    assert az.arm_calls.count("open") == 1


def test_failed_wake_reports_and_returns_to_asleep_within_ten_minutes():
    clock, store, az, api, reconcile = rig(healthy_app=False)
    t0 = clock()
    api.wake({"recaptcha_token": "good"}, ORIGIN)
    while not (intent(store).desired == "asleep" and intent(store).asleep_done):
        reconcile()
        clock.sleep(60)
    assert "wake_failed" in store.kinds()
    assert az.restricted and az.replicas == 0
    assert clock() - t0 <= 600


# ---- ownership ----

def test_takeover_waits_for_a_pending_operation_before_acting():
    clock, store, az, api, reconcile = rig(arm_seconds=200)
    handle = az.set_restricted(False)                     # an old owner's operation, still running
    entity, etag = store.read()
    store.write(entity_of(intent_of(entity), {"epoch": 3, "op": {
        "kind": "open_ingress", "state": "accepted", "url": handle.url, "issued_at": clock()}}), etag)
    api.wake({"recaptcha_token": "good"}, ORIGIN)
    calls_before = list(az.arm_calls)
    reconcile()
    assert "takeover_pending_op" in store.kinds()
    assert az.arm_calls[:len(calls_before)] == calls_before
    assert control_of(store.read()[0])["op"] is None


def test_submitting_op_waits_for_provisioning_to_finish():
    clock, store, az, api, reconcile = rig(arm_seconds=90)
    az.set_restricted(False)                              # sent, never recorded as accepted
    entity, etag = store.read()
    store.write(entity_of(intent_of(entity), {"epoch": 1, "op": {
        "kind": "open_ingress", "state": "submitting", "issued_at": clock()}}), etag)
    start = clock()
    reconcile()
    assert clock() - start >= 90


def test_lost_lease_stops_all_further_steps():
    clock, store, az, api, reconcile = rig(arm_seconds=60)
    api.wake({"recaptcha_token": "good"}, ORIGIN)
    lease_obj = Lease(clock)
    lease_obj.lose_at = clock() + 30
    out = Reconciler(store, az, lease_obj, clock=clock, sleep=clock.sleep).run()
    assert out == "lease_lost"
    n = len(az.arm_calls)
    clock.sleep(600)
    assert len(az.arm_calls) == n


def test_epoch_change_stops_an_old_owner():
    clock, store, az, api, reconcile = rig()
    api.wake({"recaptcha_token": "good"}, ORIGIN)
    r = Reconciler(store, az, Lease(clock), clock=clock, sleep=clock.sleep)
    assert r._take()
    entity, etag = store.read()                            # someone else took over
    store.write(entity_of(intent_of(entity), {"epoch": r.epoch + 1, "op": None}), etag)
    import pytest
    from wake.reconciler import LeaseLost
    with pytest.raises(LeaseLost):
        r._renew()


# ---- queue hygiene and divergence ----

def test_duplicates_and_older_messages_are_removed_keeping_exactly_one_current():
    clock, store, az, api, reconcile = rig()
    wake_and_settle(clock, store, az, api, reconcile)
    g = intent(store).generation
    az.put_message(g)
    az.put_message(g - 1)
    entity, etag = store.read()
    store.write(entity_of(intent_of(entity).__class__(**{**intent_of(entity).__dict__, "settled": False}),
                          control_of(entity)), etag)
    reconcile()
    assert [x for _, x in az.queue] == [g]


def test_sleep_never_deletes_a_newer_generations_message():
    clock, store, az, api, reconcile = rig()
    wake_and_settle(clock, store, az, api, reconcile)
    api.sleep()
    g = intent(store).generation
    az.put_message(g + 5)                                  # from an intent not yet recorded
    reconcile()
    assert [x for _, x in az.queue] == [g + 5]
    assert "newer_message" in store.kinds() and not intent(store).queue_cleared_at


# ---- review of 2026-10-18: tokens, pending states, wake budget, queue scans, visits ----

def test_a_use_token_never_renews_itself():
    clock, store, az, api, reconcile = rig()
    body = wake_and_settle(clock, store, az, api, reconcile)
    t = body
    for _ in range(4):
        clock.sleep(3600)
        r = api.wake({"use_token": t["use_token"]}, ORIGIN)
        if r.status != 202:
            break
        assert r.body == body                               # the same token, same expiry
        t = r.body
    assert api.use({"use_token": body["use_token"]}, ORIGIN).status == 403    # 4 h > 3 h


def test_a_token_wake_racing_a_completed_sleep_is_refused():
    clock, store, az, api, reconcile = rig()
    body = wake_and_settle(clock, store, az, api, reconcile)
    api.sleep()
    real_read = store.read
    calls = {"n": 0}

    def read():
        calls["n"] += 1
        if calls["n"] == 2:                                # between the check and the write
            entity, etag = real_read()
            store.write(entity_of(core.replace(intent_of(entity), asleep_done=True, settled=True),
                                  control_of(entity)), etag)
        return real_read()
    store.read = read
    assert api.wake({"use_token": body["use_token"]}, ORIGIN).status == 403
    store.read = real_read
    assert intent(store).desired == "asleep"


def test_provider_pending_states_are_waited_out_not_read_as_failure():
    clock, store, az, api, reconcile = rig()
    az.pending_states = ["Running", "Accepted", "Updating"]
    wake_and_settle(clock, store, az, api, reconcile)
    assert "operation_failed" not in store.kinds()
    assert az.arm_calls == ["open"]                         # nothing re-sent or conflicting


def test_submitting_op_waits_while_the_resource_is_updating():
    clock, store, az, api, reconcile = rig()
    az.pending_states = ["Updating"]
    handle = az.set_restricted(False)
    entity, etag = store.read()
    store.write(entity_of(intent_of(entity), {"epoch": 0, "op": {"kind": "open_ingress",
                "state": "submitting", "issued_at": clock()}}), etag)
    api.wake({"recaptcha_token": "good"}, ORIGIN)
    reconcile()
    assert az.ops[handle.url][2]                            # finished before anything else
    assert az.arm_calls[0] == "open" and az.arm_calls.count("open") == 1


def test_a_wake_whose_steps_keep_failing_ends_and_returns_to_asleep():
    clock, store, az, api, reconcile = rig()
    az.fail["open"] = "Failed"
    t0 = clock()
    api.wake({"recaptcha_token": "good"}, ORIGIN)
    while not intent(store).asleep_done and clock() - t0 < 1200:
        reconcile()
        clock.sleep(60)
    assert "wake_failed" in store.kinds()
    assert intent(store).asleep_done and az.replicas == 0
    assert clock() - t0 <= 600


def test_a_slow_operation_gives_the_wake_its_time_again():
    clock, store, az, api, reconcile = rig(arm_seconds=200)
    api.wake({"recaptcha_token": "good"}, ORIGIN)
    t0 = clock()
    while intent(store).desired == "awake" and not intent(store).settled and clock() - t0 < 900:
        reconcile()
    assert "slow_operation" in store.kinds() and "wake_failed" not in store.kinds()
    assert api.status().body["state"] == "awake"


def test_an_invisible_message_keeps_the_sleep_from_being_marked_done():
    clock, store, az, api, reconcile = rig()
    wake_and_settle(clock, store, az, api, reconcile)
    api.sleep()
    g = intent(store).generation
    az._queue.receive_messages(visibility_timeout=30)       # a crashed scan: now invisible
    real = az.read_actual

    def read_actual():
        a, rev = real()
        if any(x <= g for _, x in az.queue):
            assert not intent(store).queue_cleared_at       # never D while one exists
        return a, rev
    az.read_actual = read_actual
    assert reconcile() == "done"
    assert az.queue == [] and intent(store).asleep_done


def test_a_flood_of_older_messages_does_not_hide_the_current_one():
    clock, store, az, api, reconcile = rig()
    for x in range(200):                                   # more than one scan takes
        az.put_message(-1000 + x)
    wake_and_settle(clock, store, az, api, reconcile)
    assert [x for _, x in az.queue] == [intent(store).generation]
    assert not az.restricted


def test_duplicate_current_messages_alone_are_reduced_to_one():
    clock, store, az, api, reconcile = rig()
    wake_and_settle(clock, store, az, api, reconcile)
    g = intent(store).generation
    az.put_message(g)
    az.put_message(g)
    reconcile()
    assert [x for _, x in az.queue] == [g]


def test_a_stale_receipt_is_never_read_as_empty():
    clock, store, az, api, reconcile = rig()
    wake_and_settle(clock, store, az, api, reconcile)
    api.sleep()
    g = intent(store).generation
    hit = {"done": False}
    az._queue.get_queue_properties = lambda: SimpleNamespace(approximate_message_count=0)  # lagging
    real = az.read_actual

    def read_actual():
        a, rev = real()
        if any(x <= g for _, x in az.queue):
            assert not intent(store).queue_cleared_at
        return a, rev
    az.read_actual = read_actual

    def steal(batch):                                      # another reader takes the receipt
        if batch and not hit["done"]:
            hit["done"] = True
            m = az._queue.msgs[batch[0].id]
            m["receipt"] = "someone-else"
    az._queue.after_receive = steal
    assert reconcile() == "done"
    assert hit["done"] and az.queue == []


def test_a_visit_during_idle_sleep_reverses_it():
    clock, store, az, api, reconcile = rig()
    wake_and_settle(clock, store, az, api, reconcile)
    clock.sleep(core.IDLE_SECONDS + 1)
    reconcile_once = Reconciler(store, az, Lease(clock), clock=clock, sleep=lambda s: None)
    reconcile_once._idle_check(clock())
    assert intent(store).desired == "asleep" and not intent(store).asleep_done
    assert api.wake({"recaptcha_token": "good"}, ORIGIN).status == 202
    assert reconcile() == "done"
    assert intent(store).desired == "awake" and api.status().body["state"] == "awake"


def test_stale_restrict_while_awake_is_repaired_and_recorded():
    clock, store, az, api, reconcile = rig()
    wake_and_settle(clock, store, az, api, reconcile)
    az.restricted = True                                   # an old owner's late write lands
    start = clock()
    assert reconcile() == "done"
    assert "divergence" in store.kinds()
    assert not az.restricted
    assert clock() - start <= 300


def test_stale_deactivate_while_awake_is_repaired():
    clock, store, az, api, reconcile = rig()
    wake_and_settle(clock, store, az, api, reconcile)
    az.active, az.replicas = False, 0
    start = clock()
    assert reconcile() == "done"
    assert az.active and az.replicas == 1
    assert clock() - start <= 300


def test_stale_open_while_asleep_is_repaired():
    clock, store, az, api, reconcile = rig()
    wake_and_settle(clock, store, az, api, reconcile)
    api.sleep()
    reconcile()
    az.restricted = False
    assert reconcile() == "done"
    assert az.restricted and "divergence" in store.kinds()


def test_status_contract_states():
    i = core.Intent()
    assert core.status(i) == "asleep"
    i = core.wake(i, 10, "visit")
    assert core.status(i) == "waking"
    i = core.sleep(i, 20, "operator")
    assert core.status(i) == "going-to-sleep"


def test_before_the_cutover_status_says_awake_and_nothing_is_changed():
    clock, store, az, api, reconcile = rig()
    api.cfg.always_on = True
    assert api.status().body["state"] == "awake"


# ---- review of 2026-10-20: a sleep step Azure refuses (clause 11) ----

import pytest  # noqa: E402


def _sleep_with(fail, end="Failed", app_exits_after=150, **rig_args):
    clock, store, az, api, reconcile = rig(drain_seconds=app_exits_after, **rig_args)
    wake_and_settle(clock, store, az, api, reconcile)
    for kind in fail:
        az.fail[kind] = end
    api.sleep()
    t0 = clock()
    while not intent(store).asleep_done and clock() - t0 < 1200:
        reconcile()
        clock.sleep(60)                                    # the 1-minute timer
    return clock, store, az, api, reconcile, t0


@pytest.mark.parametrize("end", ["Failed", "Canceled"])
@pytest.mark.parametrize("fail", [["restrict"], ["deactivate"], ["restrict", "deactivate"]])
@pytest.mark.parametrize("app_exits_after", [35, 150, 100_000])   # responsive / killed after grace / never
def test_a_refused_sleep_step_does_not_stop_the_sleep(fail, end, app_exits_after):
    if "deactivate" in fail and app_exits_after > core.DRAIN_SECONDS:
        pytest.skip("nothing else stops a replica that never exits: see the next test")
    clock, store, az, api, reconcile, t0 = _sleep_with(fail, end, app_exits_after)
    assert intent(store).asleep_done and api.status().body["state"] == "asleep"
    assert az.replicas == 0 and az.queue == []
    assert clock() - t0 <= 600                             # asleep within 10 minutes
    if "restrict" in fail or app_exits_after > core.DRAIN_SECONDS:
        assert "operation_failed" in store.kinds()
    assert az.arm_calls.count("restrict") <= 2             # not retried in a loop


def test_a_refused_deactivate_with_a_replica_that_never_exits_is_reported_and_retried_slowly():
    reports = []
    clock, store, az, api, reconcile = rig(drain_seconds=100_000)
    wake_and_settle(clock, store, az, api, reconcile)
    az.fail["deactivate"] = "Failed"
    api.sleep()
    rec = Reconciler(store, az, Lease(clock), clock=clock, sleep=clock.sleep,
                     notify=lambda kind, detail: reports.append(kind))
    t0 = clock()
    while clock() - t0 < 1800:
        rec.run()
        clock.sleep(60)
    assert reports and "operation_failed" in reports
    assert az.arm_calls.count("deactivate") <= 1 + 1800 // core.RETRY_FAILED_SECONDS
    assert api.status().body["state"] == "going-to-sleep"  # honest: not asleep
    del az.fail["deactivate"]
    while clock() - t0 < 1800 + core.RETRY_FAILED_SECONDS + 120:
        rec.run()
        clock.sleep(60)
    assert az.replicas == 0 and intent(store).asleep_done


def test_a_refused_restriction_is_tried_again_later_and_repaired():
    clock, store, az, api, reconcile, t0 = _sleep_with(["restrict"])
    assert not az.restricted
    del az.fail["restrict"]
    for _ in range(12):
        clock.sleep(60)
        reconcile()
    assert az.restricted and intent(store).asleep_done


def test_a_wake_during_sleep_recovery_wins():
    clock, store, az, api, reconcile = rig()
    body = wake_and_settle(clock, store, az, api, reconcile)
    az.fail["restrict"] = "Failed"
    api.sleep()
    used = {}

    def use_once_refused(now):                             # a person acts during recovery
        if "operation_failed" in store.kinds() and not used:
            used["status"] = api.use({"use_token": body["use_token"]}, ORIGIN).status
            del az.fail["restrict"]
    clock.hooks.append(use_once_refused)
    reconcile()
    clock.hooks.remove(use_once_refused)
    assert used["status"] == 204
    i = intent(store)
    assert i.desired == "awake" and i.failed == ""
    reconcile()
    assert not az.restricted and az.active and az.replicas == 1
