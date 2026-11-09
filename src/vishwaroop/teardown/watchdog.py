"""The owner-operated watchdog: terminates the one approved pod at its absolute deadline (WO-027).

The owner runs it outside the pod, with a key the coding agent and the launcher never see. It is
built so that it cannot act on any other pod: the approved pod id is fixed when it is constructed,
and no method takes a pod id. It never stops a pod (a stop leaves volume disk billing); it only
terminates, retries on no answer, and is idempotent: terminating a pod that is already gone is a
no-op. Every poll appends the pod's status to its log, which the read-only verifier reads: that
is the heartbeat, and it bounds when compute ended even while the verifier is not watching.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

POD_ID = re.compile(r"^[A-Za-z0-9-]{4,64}$")


class PodApi(Protocol):
    now: int

    def get_pod(self, key: str, pod_id: str) -> dict[str, object] | None: ...

    def terminate(self, key: str, pod_id: str) -> None: ...


@dataclass
class Watchdog:
    """One approved pod, one absolute deadline, one owner key."""

    approved_pod_id: str
    deadline: int
    key: str
    poll_s: int = 60
    running: bool = True
    last_heartbeat: int = -1
    last_poll: int = -(10**9)
    log: list[tuple[int, str]] = field(default_factory=list)
    done: bool = False

    def __post_init__(self) -> None:
        if not POD_ID.match(self.approved_pod_id):
            raise ValueError(f"not a pod id: {self.approved_pod_id!r}")

    def tick(self, api: PodApi) -> None:
        """One poll, if due. Down (``running`` false) means no heartbeat and no action."""
        if not self.running or self.done or api.now - self.last_poll < self.poll_s:
            return
        self.last_poll = api.now
        self.last_heartbeat = api.now
        try:
            pod = api.get_pod(self.key, self.approved_pod_id)
        except TimeoutError:
            self.log.append((api.now, "read timed out; retry next poll"))
            return
        self.log.append((api.now, f"status {'gone' if pod is None else pod.get('status')}"))
        if pod is None:
            self.log.append((api.now, "approved pod is gone"))
            self.done = True
            return
        if api.now < self.deadline:
            return
        try:
            api.terminate(self.key, self.approved_pod_id)
            self.log.append((api.now, f"terminate sent; pod was {pod.get('status')}"))
        except TimeoutError:
            self.log.append((api.now, "terminate timed out; retry next poll"))
