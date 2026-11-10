import pytest

from deploy.scale_check import ready, scale


def app(state="Succeeded", latest="r2", ready_rev="r2", poll=1, cool=30):
    return {"properties": {"provisioningState": state, "latestRevisionName": latest,
                           "latestReadyRevisionName": ready_rev,
                           "template": {"scale": {"pollingInterval": poll, "cooldownPeriod": cool}}}}


@pytest.mark.parametrize("a,ok", [(app(), True), (app(ready_rev="r1"), False), (app(latest="", ready_rev=""), False),
                                  (app(latest=None, ready_rev=None), False), (app(state="InProgress"), False)])
def test_ready_needs_the_new_revision_ready(a, ok):
    assert ready(a) is ok


@pytest.mark.parametrize("a,ok", [(app(), True), (app(poll=30), False), (app(cool=300), False), ({}, False)])
def test_scale_needs_exactly_one_and_thirty(a, ok):
    assert scale(a) is ok
