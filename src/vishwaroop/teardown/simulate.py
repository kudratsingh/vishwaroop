"""Simulated teardown scenarios for an owner-operated pod (WO-027). Fabricated provider; no network.

``python -m vishwaroop.teardown.simulate`` runs every scenario in a ledgered run and writes
``teardown_simulation.json``; ``--no-ledger`` prints the table only (used by the tests).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .provider import HOUR, FakeProvider, ForbiddenError, InPodTimer, ProviderTimeoutError
from .verify import Approval, Verifier
from .watchdog import Watchdog

POD = "pod-approved"
OTHER = "pod-other"
OWNER_KEY = "owner-write"  # held by the owner's watchdog only
READ_KEY = "agent-read"  # the agent's and the launcher's key
DEADLINE = 4 * HOUR
HORIZON = DEADLINE + 6 * HOUR
CONTAINER_GB = 100
STEP = 10


@dataclass
class Scenario:
    name: str
    question: str
    timer_mode: str = "absolute"
    timer_action: str = "stop"
    volume_gb: int = 0
    network_volume: bool = False
    billing_delay_s: int = 0
    settle_s: int = 2 * HOUR
    fail_mutations: int = 0
    watchdog_down: tuple[int, int] | None = None
    verifier_down: tuple[int, int] | None = None
    events: dict[int, str] = field(default_factory=dict)
    extra_billing_s: int = 0
    billing_batch: bool = False


SCENARIOS = [
    Scenario("baseline", "No faults: does the watchdog terminate at the deadline?"),
    Scenario(
        "owner-ends-early",
        "The owner terminates at 2 h: does verification still close?",
        events={2 * HOUR: "owner-terminate"},
    ),
    Scenario("timer-dies", "The in-pod timer is killed at 10 min.", events={600: "kill-timer"}),
    Scenario(
        "restart", "The container restarts at 3 h; watchdog up.", events={3 * HOUR: "restart"}
    ),
    Scenario(
        "restart, relative timer, watchdog down",
        "Restart at 3 h with a timer relative to container start and no watchdog.",
        timer_mode="relative",
        watchdog_down=(0, HORIZON),
        events={3 * HOUR: "restart"},
    ),
    Scenario(
        "restart, absolute timer, watchdog down",
        "Restart at 3 h with a timer to an absolute deadline and no watchdog.",
        watchdog_down=(0, HORIZON),
        events={3 * HOUR: "restart"},
    ),
    Scenario(
        "ssh drop",
        "The agent's session (and the verifier in it) is lost from 1 h to 6 h.",
        verifier_down=(1 * HOUR, 6 * HOUR),
    ),
    Scenario(
        "ssh drop + timer dies + restart",
        "Session lost from 1 h, timer killed at 1.5 h, restart at 3 h; watchdog up.",
        verifier_down=(1 * HOUR, 6 * HOUR),
        events={5400: "kill-timer", 3 * HOUR: "restart"},
    ),
    Scenario(
        "watchdog down, timer dead",
        "Both bounds gone: what does the verifier do?",
        watchdog_down=(0, HORIZON),
        events={600: "kill-timer"},
    ),
    Scenario(
        "watchdog asleep, back late",
        "The watchdog is down from 3 h to 5 h (a sleeping laptop); timer dead.",
        watchdog_down=(3 * HOUR, 5 * HOUR),
        events={600: "kill-timer"},
    ),
    Scenario(
        "terminate timeouts", "The first five terminate calls get no answer.", fail_mutations=5
    ),
    Scenario(
        "billing lag 90 min",
        "Billing records lag 90 min; settle window 2 h.",
        billing_delay_s=90 * 60,
    ),
    Scenario(
        "hourly posting, short settle window",
        "Billing posts whole hour buckets 1 h late; settle window only 30 min.",
        billing_delay_s=HOUR,
        billing_batch=True,
        settle_s=30 * 60,
    ),
    Scenario(
        "network volume attached", "The pod was created with a network volume.", network_volume=True
    ),
    Scenario(
        "volume disk, stop only",
        "A 20 GB volume disk; no watchdog; the timer stops the pod.",
        volume_gb=20,
        watchdog_down=(0, HORIZON),
    ),
    Scenario(
        "provider over-bills",
        "The provider bills 15 extra minutes of compute.",
        extra_billing_s=15 * 60,
    ),
]


def run(s: Scenario) -> dict[str, Any]:
    api = FakeProvider(billing_delay_s=s.billing_delay_s, billing_batch=s.billing_batch)
    api.keys = {OWNER_KEY: "owner", READ_KEY: "read"}
    if s.network_volume:
        api.owner_create_network_volume("nv-1", 50)
    api.owner_create(
        POD,
        container_gb=CONTAINER_GB,
        volume_gb=s.volume_gb,
        network_volume_id="nv-1" if s.network_volume else None,
        deadline=DEADLINE,
        timer=InPodTimer(s.timer_mode, DEADLINE, s.timer_action),
    )
    api.owner_create(OTHER, container_gb=20)  # the owner's other pod, never approved
    watchdog = Watchdog(POD, DEADLINE, OWNER_KEY)
    approval = Approval(
        POD, DEADLINE, reservation_usd=6.0, gpu_per_hour=api.rates.gpu_per_hour, settle_s=s.settle_s
    )
    verifier = Verifier(approval, READ_KEY)
    refusals = verifier.preflight(api, CONTAINER_GB)
    saved: dict[str, Any] | None = None
    read_only_mutation = "allowed"
    try:
        api.terminate(READ_KEY, POD)
    except ForbiddenError:
        read_only_mutation = "refused (403)"
    api.fail_mutations = s.fail_mutations
    ended_at: int | None = None
    verified_at: int | None = None
    false_settle = False
    while api.now < HORIZON:
        if s.events.get(api.now) == "kill-timer":
            api.kill_timer(POD)
        elif s.events.get(api.now) == "restart" and POD in api.pods:
            api.restart(POD)
        elif s.events.get(api.now) == "owner-terminate":
            api.terminate(OWNER_KEY, POD)
        down = s.watchdog_down
        watchdog.running = not (down and down[0] <= api.now < down[1])
        with contextlib.suppress(ProviderTimeoutError):
            watchdog.tick(api)
        vdown = s.verifier_down
        if vdown and api.now == vdown[0]:
            saved = json.loads(json.dumps(verifier.state))  # what the launcher's ledger holds
        if vdown and api.now == vdown[1] and saved is not None:
            verifier = Verifier(approval, READ_KEY, state=saved)  # a fresh process resumes
        if not (vdown and vdown[0] <= api.now < vdown[1]):
            verifier.tick(api, watchdog.last_heartbeat)
        if ended_at is None and (POD not in api.pods or api.pods[POD].status != "RUNNING"):
            ended_at = api.now
        if POD not in api.pods and not (vdown and vdown[0] <= api.now < vdown[1]):
            interim = verifier.verdict(api, watchdog.log)
            false_settle |= interim["billing_settled"] and not interim["reconciled"]
            if interim["verified"] and verified_at is None:
                verified_at = api.now
        api.advance(STEP, STEP)
        if s.extra_billing_s and api.now == DEADLINE + 30 * 60:
            api.ledger.append((0, POD, api.rates.gpu_per_hour * s.extra_billing_s / HOUR, 0.0))
    verdict = verifier.verdict(api, watchdog.log)
    last_hour = [g + d for t, r, g, d in api.ledger if t >= HORIZON - HOUR and r in (POD, "nv-1")]
    other_mutated = any(c[0] in ("terminate", "stop") and c[2] == OTHER for c in api.calls)
    past = [
        t
        for t, (_, r) in zip(verdict["alarm_times"], verifier.state["alarms"], strict=True)
        if "past deadline" in r
    ]
    return {
        "scenario": s.name,
        "deadline_met": ended_at is not None and ended_at <= DEADLINE + approval.grace_s,
        "verified_min_after_deadline": None
        if verified_at is None
        else round((verified_at - DEADLINE) / 60, 1),
        "first_deadline_alarm_min": None if not past else round((past[0] - DEADLINE) / 60, 1),
        "stable_but_unreconciled_seen": false_settle,
        "question": s.question,
        "preflight_refusals": refusals,
        "read_only_key_mutation": read_only_mutation,
        "other_pod_touched": other_mutated,
        "pod_end": "terminated"
        if POD in api.terminated
        else (api.pods[POD].status if POD in api.pods else "gone"),
        "compute_ended_min_after_deadline": None
        if ended_at is None
        else round((ended_at - DEADLINE) / 60, 1),
        "standing_usd_per_hour_at_end": round(sum(last_hour), 4),
        **verdict,
    }


def table(results: list[dict[str, Any]]) -> str:
    rows = [
        "| Scenario | Pod at end | Compute ended (min vs deadline) | Deadline met | "
        "Standing $/h at end | Billed $ | Expected $ range | Verified (min vs deadline) | "
        "First overrun alarm (min) | Stable but unreconciled, caught | Alarms / refusals |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        notes = "; ".join(r["preflight_refusals"] + r["alarms"]) or "none"
        ended = r["compute_ended_min_after_deadline"]
        rows.append(
            f"| {r['scenario']} | {r['pod_end']} | {'still running' if ended is None else ended} | "
            f"{'yes' if r['deadline_met'] else 'no'} | "
            f"{r['standing_usd_per_hour_at_end']} | {r['billed_usd']} | "
            f"{r['expected_range_usd'][0]}to{r['expected_range_usd'][1]} | "
            f"{'yes, at ' + str(r['verified_min_after_deadline']) if r['verified'] else 'no'} | "
            f"{r['first_deadline_alarm_min'] if r['first_deadline_alarm_min'] is not None else '—'}"
            f" | {'yes' if r['stable_but_unreconciled_seen'] else 'no'} | {notes} |"
        )
    return "\n".join(rows)


def main(argv: list[str] | None = None, runner: Callable[[Scenario], dict[str, Any]] = run) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-ledger", action="store_true")
    args = parser.parse_args(argv)
    results = [runner(s) for s in SCENARIOS]
    if args.no_ledger:
        print(table(results))
        return 0
    from ..sim.runlog import ledgered_run, require_code_root

    try:
        require_code_root()
        with ledgered_run(
            purpose="WO-027 teardown simulation (fabricated provider; mocked/fixture)",
            config={
                "scenarios": [s.name for s in SCENARIOS],
                "deadline_s": DEADLINE,
                "horizon_s": HORIZON,
                "step_s": STEP,
            },
            seeds={},
            env_lock={},
        ) as run_:
            if run_.dirty:
                raise ValueError("commit first, so the code note stays true")
            out = run_.directory / "teardown_simulation.json"
            with out.open("x", encoding="utf-8") as stream:
                json.dump({"code": run_.code_note, "results": results}, stream, indent=2)
                stream.write("\n")
            run_.note = f"{sum(r['verified'] for r in results)} of {len(results)} verified"
            print(table(results))
            print(run_.directory)
    except (ValueError, OSError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
