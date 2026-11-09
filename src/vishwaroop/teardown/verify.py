"""The read-only verifier: preflight, monitoring, teardown verification and reconciliation (WO-027).

It holds only a read-only key, so it cannot create, stop or terminate anything. It raises alarms
for the owner; it never acts. Its state is a plain dictionary that can be saved and restored, so a
lost session (an SSH drop, a closed laptop) resumes from provider reads without losing evidence.

Teardown counts as verified only when all of these hold:
1. the approved pod is gone on two reads at least one poll apart;
2. the pod's billing total is unchanged across two reads at least ``settle_s`` apart, with
   ``settle_s`` at least the provider's billing lag;
3. no network volume existed at preflight or appeared during the run, and none bills now;
4. the billed total reconciles with the expected charge within tolerance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

HOUR = 3600


class ReadApi(Protocol):
    now: int

    def get_pod(self, key: str, pod_id: str) -> dict[str, Any] | None: ...

    def pod_billing(self, key: str, pod_id: str) -> list[dict[str, float]]: ...

    def list_network_volumes(self, key: str) -> dict[str, int]: ...

    def network_volume_billing(self, key: str) -> float: ...


@dataclass
class Approval:
    """What the owner approved for one paid run."""

    pod_id: str
    deadline: int
    reservation_usd: float
    gpu_per_hour: float
    container_gb_month: float = 0.10
    grace_s: int = 600
    settle_s: int = 2 * HOUR
    max_watchdog_silence_s: int = 300


@dataclass
class Verifier:
    approval: Approval
    key: str
    poll_s: int = 60
    state: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.state.setdefault("alarms", [])
        self.state.setdefault("first_seen_running", None)
        self.state.setdefault("last_seen_running", None)
        self.state.setdefault("gone_reads", [])
        self.state.setdefault("billing_reads", [])
        self.state.setdefault("preflight", None)
        self.state.setdefault("last_poll", -(10**9))
        self.state.setdefault("volumes_at_preflight", None)
        self.state.setdefault("container_gb", 0)
        self.state.setdefault("last_status", None)

    def _alarm(self, now: int, reason: str) -> None:
        if not any(r == reason for _, r in self.state["alarms"]):
            self.state["alarms"].append((now, reason))

    def preflight(self, api: ReadApi, container_gb: int) -> list[str]:
        """Refusals before the agent runs anything; an empty list means go."""
        pod = api.get_pod(self.key, self.approval.pod_id)
        refusals = []
        if pod is None:
            refusals.append("approved pod not found")
        else:
            if pod.get("networkVolumeId"):
                refusals.append("a network volume is attached; it bills until deleted")
            if pod.get("volumeInGb", 0):
                refusals.append("the pod has a volume disk; a stop would keep billing it")
            env_deadline = pod.get("env", {}).get("VISHWAROOP_DEADLINE_UTC_EPOCH")
            if env_deadline is None or int(env_deadline) > self.approval.deadline:
                refusals.append("the in-pod backup timer's absolute deadline is missing or late")
            if pod.get("containerDiskInGb") != container_gb:
                refusals.append("container disk differs from the approval")
        self.state["container_gb"] = container_gb
        volumes = api.list_network_volumes(self.key)
        self.state["volumes_at_preflight"] = sorted(volumes)
        if volumes:
            refusals.append(f"network volumes exist and bill: {sorted(volumes)}")
        self.state["preflight"] = refusals
        return refusals

    def tick(self, api: ReadApi, watchdog_heartbeat: int) -> None:
        now = api.now
        if now - self.state["last_poll"] < self.poll_s:
            return
        self.state["last_poll"] = now
        pod = api.get_pod(self.key, self.approval.pod_id)
        self.state["last_status"] = None if pod is None else pod["status"]
        if pod is not None and pod["status"] == "RUNNING":
            if self.state["first_seen_running"] is None:
                self.state["first_seen_running"] = now
            self.state["last_seen_running"] = now
        if pod is None:
            self.state["gone_reads"].append(now)
        elif now > self.approval.deadline + self.approval.grace_s:
            self._alarm(now, f"pod {pod['status']} past deadline plus grace; owner must act")
        if pod is not None and now - watchdog_heartbeat > self.approval.max_watchdog_silence_s:
            self._alarm(now, "watchdog silent; the in-pod timer is the only bound left")
        billed = sum(b["totalAmount"] for b in api.pod_billing(self.key, self.approval.pod_id))
        self.state["billing_reads"].append((now, billed))
        if billed > self.approval.reservation_usd:
            self._alarm(now, "billing above the reservation")

    def verdict(
        self, api: ReadApi, watchdog_log: list[tuple[int, str]] | None = None
    ) -> dict[str, Any]:
        """Whether teardown is verified now, with the reconciliation.

        ``watchdog_log`` is the owner watchdog's append-only log, readable by the verifier. Its
        "terminate sent" time bounds the end of compute when the verifier itself was not watching.
        """
        gone = self.state["gone_reads"]
        pod_gone = len(gone) >= 2 and gone[-1] - gone[0] >= self.poll_s
        reads = self.state["billing_reads"]
        settled = False
        if pod_gone and reads:
            last_t, last_amount = reads[-1]
            earlier = [a for t, a in reads if t >= gone[0] and last_t - t >= self.approval.settle_s]
            settled = bool(earlier) and abs(earlier[-1] - last_amount) < 1e-9
        volumes_now = api.list_network_volumes(self.key)
        volumes_ok = not volumes_now and not self.state["volumes_at_preflight"]
        billed = reads[-1][1] if reads else 0.0
        # Evidence of when compute ran: the verifier's own reads, and the owner watchdog's
        # per-poll status log (read-only), which keeps watching when this verifier's session drops.
        log = watchdog_log or []
        running = [t for t, m in log if m == "status RUNNING"]
        for own in (self.state["first_seen_running"], self.state["last_seen_running"]):
            if own is not None:
                running.append(own)
        first = min(running) if running else None
        last = max(running) if running else None
        expected = low = high = 0.0
        window = None
        if first is not None and last is not None:
            disk_per_hour = self.state["container_gb"] * self.approval.container_gb_month / 730.0
            per_s = (self.approval.gpu_per_hour + disk_per_hour) / HOUR
            stopped = [t for t in gone if t > last] + [
                t for t, m in log if m.startswith("status ") and m != "status RUNNING" and t > last
            ]
            end = min(stopped) if stopped else last + self.poll_s
            window = end - last
            # Compute ran at least from the first running sighting to the last, and at most from a
            # poll before the first to the first sighting of the pod stopped or gone.
            low = (last - first) * per_s
            high = (end - first + self.poll_s) * per_s
            expected = (low + high) / 2
        reconciled = low - 1e-9 <= billed <= high if first is not None else False
        # The end of compute must be pinned to within three polls by someone's observation.
        tight = window is not None and window <= 3 * self.poll_s
        verified = pod_gone and settled and volumes_ok and reconciled and tight
        return {
            "verified": verified,
            "pod_gone": pod_gone,
            "billing_settled": settled,
            "network_volumes_clear": volumes_ok,
            "reconciled": reconciled,
            "reconciliation_tight": tight,
            "stopped_not_terminated": self.state["last_status"] == "EXITED",
            "billed_usd": round(billed, 4),
            "expected_usd": round(expected, 4),
            "expected_range_usd": [round(low, 4), round(high, 4)],
            "end_of_compute_window_s": window,
            "alarms": [reason for _, reason in self.state["alarms"]],
            "alarm_times": [time for time, _ in self.state["alarms"]],
        }
