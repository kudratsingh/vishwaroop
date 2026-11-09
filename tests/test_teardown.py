"""WO-027: teardown for owner-operated pods, against the fabricated provider (mocked/fixture)."""

from __future__ import annotations

import inspect
import json
from typing import Any

import pytest

from vishwaroop.teardown import simulate
from vishwaroop.teardown.provider import FakeProvider, ForbiddenError, InPodTimer
from vishwaroop.teardown.verify import Approval, Verifier
from vishwaroop.teardown.watchdog import Watchdog

RESULTS: dict[str, dict[str, Any]] = {s.name: simulate.run(s) for s in simulate.SCENARIOS}
POLL_MIN = 1.0


def test_every_scenario_keeps_the_agent_read_only_and_the_other_pod_untouched() -> None:
    for result in RESULTS.values():
        assert result["read_only_key_mutation"] == "refused (403)"
        assert result["other_pod_touched"] is False


@pytest.mark.parametrize(
    "name",
    [
        "baseline",
        "timer-dies",
        "restart",
        "ssh drop",
        "ssh drop + timer dies + restart",
        "terminate timeouts",
        "billing lag 90 min",
    ],
)
def test_with_the_watchdog_up_compute_ends_at_the_deadline_and_teardown_verifies(name: str) -> None:
    r = RESULTS[name]
    assert r["deadline_met"] and r["verified"] and r["pod_end"] == "terminated"
    assert r["standing_usd_per_hour_at_end"] == 0
    assert r["compute_ended_min_after_deadline"] <= 6 * POLL_MIN  # the five timeouts, then success


def test_a_restart_moves_a_relative_timer_but_not_an_absolute_one() -> None:
    relative = RESULTS["restart, relative timer, watchdog down"]
    absolute = RESULTS["restart, absolute timer, watchdog down"]
    assert relative["deadline_met"] is False and relative["compute_ended_min_after_deadline"] == 180
    assert absolute["deadline_met"] is True and absolute["compute_ended_min_after_deadline"] == 0


def test_a_stop_alone_is_bounded_but_not_verified_and_the_owner_is_alarmed() -> None:
    r = RESULTS["restart, absolute timer, watchdog down"]
    assert r["pod_end"] == "EXITED" and r["standing_usd_per_hour_at_end"] == 0
    assert not r["verified"]
    assert r["first_deadline_alarm_min"] is not None and r["first_deadline_alarm_min"] <= 11


def test_with_both_bounds_gone_the_verifier_alarms_within_grace_and_never_verifies() -> None:
    r = RESULTS["watchdog down, timer dead"]
    assert r["pod_end"] == "RUNNING" and not r["verified"] and not r["deadline_met"]
    assert r["first_deadline_alarm_min"] <= 10 + POLL_MIN
    assert any("watchdog silent" in a for a in r["alarms"])
    assert any("above the reservation" in a for a in r["alarms"])


def test_a_late_watchdog_is_verified_but_reported_as_a_missed_deadline() -> None:
    r = RESULTS["watchdog asleep, back late"]
    assert r["verified"] and not r["deadline_met"]
    assert r["compute_ended_min_after_deadline"] == 60


def test_stable_but_incomplete_billing_is_caught_by_reconciliation() -> None:
    r = RESULTS["hourly posting, short settle window"]
    assert r["stable_but_unreconciled_seen"] is True
    assert r["verified"]  # only once the last bucket posted and reconciled


def test_storage_that_outlives_the_pod_is_refused_and_never_verified() -> None:
    nv = RESULTS["network volume attached"]
    assert any("network volume" in x for x in nv["preflight_refusals"])
    assert not nv["network_volumes_clear"] and not nv["verified"]
    assert nv["standing_usd_per_hour_at_end"] > 0
    disk = RESULTS["volume disk, stop only"]
    assert any("volume disk" in x for x in disk["preflight_refusals"])
    assert disk["standing_usd_per_hour_at_end"] > 0 and not disk["verified"]


def test_over_billing_fails_reconciliation() -> None:
    r = RESULTS["provider over-bills"]
    assert r["pod_gone"] and not r["reconciled"] and not r["verified"]
    assert r["billed_usd"] > r["expected_range_usd"][1]


def test_the_watchdog_cannot_be_pointed_at_another_pod() -> None:
    assert list(inspect.signature(Watchdog.tick).parameters) == ["self", "api"]
    with pytest.raises(ValueError, match="not a pod id"):
        Watchdog("../all", 0, "k")
    api = FakeProvider()
    api.keys = {"owner": "owner"}
    api.owner_create("pod-a", deadline=10)
    api.owner_create("pod-b")
    dog = Watchdog("pod-a", 10, "owner", poll_s=10)
    for _ in range(5):
        dog.tick(api)
        api.advance(10)
    assert "pod-a" in api.terminated and "pod-b" in api.pods


def test_a_read_only_key_cannot_stop_or_terminate() -> None:
    api = FakeProvider()
    api.keys = {"r": "read"}
    api.owner_create("pod-a")
    for action in (api.stop, api.terminate):
        with pytest.raises(ForbiddenError):
            action("r", "pod-a")
    assert api.pods["pod-a"].status == "RUNNING"


def test_verifier_state_survives_a_lost_session_as_plain_json() -> None:
    api = FakeProvider()
    api.keys = {"r": "read"}
    api.owner_create("pod-a", container_gb=100, deadline=600, timer=InPodTimer("absolute", 600))
    approval = Approval("pod-a", 600, reservation_usd=1.0, gpu_per_hour=1.19)
    verifier = Verifier(approval, "r")
    assert verifier.preflight(api, 100) == []
    verifier.tick(api, watchdog_heartbeat=0)
    restored = Verifier(approval, "r", state=json.loads(json.dumps(verifier.state)))
    assert restored.state == json.loads(json.dumps(verifier.state))
