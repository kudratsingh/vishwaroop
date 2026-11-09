"""A fabricated pod provider with a clock, per-second billing and fault injection (WO-027).

It models the Runpod facts the teardown design depends on (read 2026-11-09 from Runpod's docs via
its MCP concept store), not Runpod itself:
- pods are billed per second for compute, container disk and volume disk;
- a stopped (``EXITED``) pod is not billed for compute or container disk, but its volume disk is
  billed at a higher rate; only termination ends every pod charge;
- a network volume is billed from creation until deletion, attached or not;
- billing history comes in hour buckets per pod and may lag the clock;
- a terminated pod is gone: reads return nothing;
- API keys carry their access: a read-only key cannot mutate (403).

Every rate here is a simulation parameter, not a quote.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

HOUR = 3600
MONTH_HOURS = 730.0


class ForbiddenError(PermissionError):
    """The key lacks access to this action (HTTP 403)."""


class ProviderTimeoutError(TimeoutError):
    """The provider did not answer; the action may or may not have happened."""


@dataclass(frozen=True)
class Rates:
    """Simulation rates in USD. GPU from WO-025's quote; disk rates are assumptions."""

    gpu_per_hour: float = 1.19
    container_gb_month: float = 0.10
    volume_gb_month_running: float = 0.10
    volume_gb_month_stopped: float = 0.20
    network_gb_month: float = 0.07


@dataclass
class InPodTimer:
    """The backup timer, a child of the container's main process.

    ``mode`` "relative" sleeps a duration from container start, so a restart starts it again;
    "absolute" sleeps until a fixed epoch passed in the environment, so a restart cannot move it.
    ``action`` is what the pod-scoped key does when it fires.
    """

    mode: str
    seconds: int
    action: str = "stop"
    alive: bool = True
    due: int = 0

    def arm(self, now: int, deadline: int) -> None:
        self.alive = True
        self.due = now + self.seconds if self.mode == "relative" else deadline


@dataclass
class Pod:
    pod_id: str
    status: str
    container_gb: int
    volume_gb: int
    network_volume_id: str | None
    env: dict[str, str]
    timer: InPodTimer | None
    created: int
    container_started: int


@dataclass
class FakeProvider:
    """Clock, pods, keys, billing and injected faults."""

    rates: Rates = field(default_factory=Rates)
    billing_delay_s: int = 0
    # True: a bucket appears only once complete and ``billing_delay_s`` old (hourly posting).
    billing_batch: bool = False
    pod_key_can_terminate: bool = False
    now: int = 0
    pods: dict[str, Pod] = field(default_factory=dict)
    terminated: dict[str, int] = field(default_factory=dict)
    network_volumes: dict[str, int] = field(default_factory=dict)
    keys: dict[str, str] = field(default_factory=dict)
    # (time, resource id, gpu USD, disk USD) per accrual step
    ledger: list[tuple[int, str, float, float]] = field(default_factory=list)
    fail_mutations: int = 0
    calls: list[tuple[str, str, str]] = field(default_factory=list)

    # --- owner actions (outside the API keys the agent or watchdog hold) ---
    def owner_create(
        self,
        pod_id: str,
        *,
        container_gb: int = 100,
        volume_gb: int = 0,
        network_volume_id: str | None = None,
        deadline: int = 0,
        timer: InPodTimer | None = None,
    ) -> Pod:
        env = {"VISHWAROOP_DEADLINE_UTC_EPOCH": str(deadline)} if deadline else {}
        pod = Pod(
            pod_id,
            "RUNNING",
            container_gb,
            volume_gb,
            network_volume_id,
            env,
            timer,
            self.now,
            self.now,
        )
        if timer:
            timer.arm(self.now, deadline)
        self.pods[pod_id] = pod
        return pod

    def owner_create_network_volume(self, volume_id: str, gb: int) -> None:
        self.network_volumes[volume_id] = gb

    # --- faults ---
    def restart(self, pod_id: str) -> None:
        """The container restarts: the main process and its children start again."""
        pod = self.pods[pod_id]
        pod.container_started = self.now
        if pod.timer:
            deadline = int(pod.env.get("VISHWAROOP_DEADLINE_UTC_EPOCH", "0"))
            pod.timer.arm(self.now, deadline)

    def kill_timer(self, pod_id: str) -> None:
        timer = self.pods[pod_id].timer
        if timer:
            timer.alive = False

    # --- the API, by key ---
    def _scope(self, key: str) -> str:
        if key not in self.keys:
            raise ForbiddenError("unknown key (401)")
        return self.keys[key]

    def get_pod(self, key: str, pod_id: str) -> dict[str, Any] | None:
        self._scope(key)
        self.calls.append(("get", key, pod_id))
        pod = self.pods.get(pod_id)
        if pod is None:
            return None
        return {
            "id": pod.pod_id,
            "status": pod.status,
            "containerDiskInGb": pod.container_gb,
            "volumeInGb": pod.volume_gb,
            "networkVolumeId": pod.network_volume_id,
            "env": dict(pod.env),
            "cost": self.rates.gpu_per_hour if pod.status == "RUNNING" else 0.0,
        }

    def list_pods(self, key: str) -> list[str]:
        self._scope(key)
        return sorted(self.pods)

    def list_network_volumes(self, key: str) -> dict[str, int]:
        self._scope(key)
        return dict(self.network_volumes)

    def _mutate(self, key: str, pod_id: str, action: str, *, pod_scoped: bool = False) -> None:
        scope = "pod" if pod_scoped else self._scope(key)
        if scope == "read":
            raise ForbiddenError(f"read-only key cannot {action} (403)")
        self.calls.append((action, key, pod_id))
        if self.fail_mutations > 0:
            self.fail_mutations -= 1
            raise ProviderTimeoutError(f"{action} {pod_id}: no answer")
        if pod_id not in self.pods:
            return  # idempotent: already gone
        if action == "terminate":
            del self.pods[pod_id]
            self.terminated[pod_id] = self.now
        elif action == "stop":
            pod = self.pods[pod_id]
            pod.status = "EXITED"
            if pod.timer is not None:
                pod.timer.alive = False

    def terminate(self, key: str, pod_id: str) -> None:
        self._mutate(key, pod_id, "terminate")

    def stop(self, key: str, pod_id: str) -> None:
        self._mutate(key, pod_id, "stop")

    def pod_billing(self, key: str, pod_id: str) -> list[dict[str, float]]:
        """Hour buckets for one pod, as visible now (accrual up to ``now - billing_delay_s``)."""
        self._scope(key)
        horizon = self.now - self.billing_delay_s
        if self.billing_batch:
            horizon = horizon // HOUR * HOUR - 1  # only buckets that ended by the horizon
        buckets: dict[int, list[float]] = {}
        for time, resource, gpu, disk in self.ledger:
            if resource == pod_id and time <= horizon:
                bucket = buckets.setdefault(time // HOUR * HOUR, [0.0, 0.0])
                bucket[0] += gpu
                bucket[1] += disk
        return [
            {"startTime": start, "gpuAmount": g, "diskAmount": d, "totalAmount": g + d}
            for start, (g, d) in sorted(buckets.items())
        ]

    def network_volume_billing(self, key: str) -> float:
        self._scope(key)
        horizon = self.now - self.billing_delay_s
        return sum(
            g + d for t, r, g, d in self.ledger if r in self.network_volumes and t <= horizon
        )

    # --- time ---
    def advance(self, seconds: int, step: int = 10) -> None:
        for _ in range(seconds // step):
            self._accrue(step)
            self.now += step
            self._fire_timers()

    def _accrue(self, step: int) -> None:
        r = self.rates
        for pod in self.pods.values():
            if pod.status == "RUNNING":
                gpu = r.gpu_per_hour * step / HOUR
                disk = (
                    (
                        pod.container_gb * r.container_gb_month
                        + pod.volume_gb * r.volume_gb_month_running
                    )
                    * step
                    / (MONTH_HOURS * HOUR)
                )
            else:
                gpu = 0.0
                disk = pod.volume_gb * r.volume_gb_month_stopped * step / (MONTH_HOURS * HOUR)
            self.ledger.append((self.now, pod.pod_id, gpu, disk))
        for volume, gb in self.network_volumes.items():
            amount = gb * r.network_gb_month * step / (MONTH_HOURS * HOUR)
            self.ledger.append((self.now, volume, 0.0, amount))

    def _fire_timers(self) -> None:
        for pod in list(self.pods.values()):
            timer = pod.timer
            if timer and timer.alive and pod.status == "RUNNING" and self.now >= timer.due:
                action = (
                    "terminate"
                    if (timer.action == "terminate" and self.pod_key_can_terminate)
                    else "stop"
                )
                try:
                    self._mutate("pod-scoped", pod.pod_id, action, pod_scoped=True)
                except ProviderTimeoutError:
                    continue
