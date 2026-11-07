"""M3's scene engine: seed partitions, scene snapshots, operators, the mismatch injector and the
deterministic scene-consistency checker (``evals/M3-protocol.md``, ``evals/M3-exit-tests.json``).

``protocol``, ``operators`` and the rule parts of ``checker`` are standard library only, so they run
on the CPU tier. Frame work (``masks``, ``inject``, frame measurement and snapshot renders) needs
numpy and scipy from the robotics environment, and is imported only where it is used.
"""

from __future__ import annotations
