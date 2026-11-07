"""M3's seed blocks, partitions and identities, as ``evals/M3-protocol.md`` sections 2 and 5 freeze
them. ``m3-protocol-2`` (``evals/M3-protocol-2.json``) keeps them and replaces only ET-M3-1.

Blocks are 1,000 seeds. Blocks 10 to 15 are train, 16 and 17 dev, 18 and 19 reserved and never
simulated. M3 never makes new data on blocks 0 to 9, which M0's protocol still governs. A training
set may read M0's train blocks (0 to 7), and never holds a dev seed (blocks 8, 9, 16, 17) or a
reserved one. Every refusal is a ``ProtocolRefusalError``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

PROTOCOL_VERSION = "m3-protocol-2"
SEEDS_PER_BLOCK = 1000
TRAIN_BLOCKS = range(10, 16)
DEV_BLOCKS = (16, 17)
RESERVED_BLOCKS = (18, 19)
M0_BLOCKS = range(10)
M0_TRAIN_BLOCKS = range(8)
M0_DEV_BLOCKS = (8, 9)
TRAINING_REFUSED_BLOCKS = (*M0_DEV_BLOCKS, *DEV_BLOCKS)
KINDS = ("synth", "eval")
_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


class ProtocolRefusalError(ValueError):
    """A seed, block or identity that ``m3-protocol-1`` does not allow where it was asked for."""


def block_of(seed: int) -> int:
    """The seed's block of 1,000. Refuses a negative seed or a non-integer."""
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ProtocolRefusalError(f"a seed is a non-negative integer, not {seed!r}")
    return seed // SEEDS_PER_BLOCK


def partition_for_seed(seed: int) -> str:
    """The partition of a seed on which M3 may make new data: ``train`` or ``dev``.

    Blocks 0 to 9 belong to M0 and get no new M3 data; blocks 18 and 19 are never simulated;
    blocks past 19 belong to nothing.
    """
    block = block_of(seed)
    if block in TRAIN_BLOCKS:
        return "train"
    if block in DEV_BLOCKS:
        return "dev"
    if block in RESERVED_BLOCKS:
        raise ProtocolRefusalError(
            f"seed {seed} is in reserved block {block}: never simulated (m3-protocol-1 section 2)"
        )
    if block in M0_BLOCKS:
        raise ProtocolRefusalError(
            f"seed {seed} is in block {block}; M3 never uses blocks 0 to 9 for new data"
        )
    raise ProtocolRefusalError(f"seed {seed} is in block {block}, outside the frozen blocks 0-19")


def scene_group_id(seed: int) -> str:
    """``m3-seed-block-<n>`` for a seed M3 may simulate; refuses the others."""
    partition_for_seed(seed)
    return f"m3-seed-block-{block_of(seed)}"


def check_training_seeds(seeds: Iterable[int]) -> list[int]:
    """Refuse a training set holding a dev seed (blocks 8, 9, 16, 17) or a reserved one.

    M0's train blocks 0 to 7 may be read, as M1 did, and M3's train blocks 10 to 15 may be used.
    Returns the seeds as a list, unchanged.
    """
    checked = []
    for seed in seeds:
        block = block_of(seed)
        if block in TRAINING_REFUSED_BLOCKS:
            raise ProtocolRefusalError(
                f"seed {seed} is in dev block {block}, which no training set may hold"
            )
        if block in RESERVED_BLOCKS:
            raise ProtocolRefusalError(f"seed {seed} is in reserved block {block}")
        if block not in TRAIN_BLOCKS and block not in M0_TRAIN_BLOCKS:
            raise ProtocolRefusalError(
                f"seed {seed} is in block {block}, outside the frozen blocks"
            )
        checked.append(seed)
    return checked


def family_id(kind: str, name: str) -> str:
    """``m3-<kind>-<name>``: ``synth`` for operator data, ``eval`` for evaluation families."""
    if kind not in KINDS:
        raise ProtocolRefusalError(f"family kind {kind!r} is not one of {KINDS}")
    if not _NAME.fullmatch(name):
        raise ProtocolRefusalError(f"family name {name!r} is not lower-case words joined by '-'")
    return f"m3-{kind}-{name}"


def family_partition(family: str) -> str:
    """The one partition a family lies in: operator data is train, evaluation families dev."""
    if family.startswith("m3-synth-"):
        return "train"
    if family.startswith("m3-eval-"):
        return "dev"
    raise ProtocolRefusalError(f"{family} is not an M3 family id")


def check_family_seed(family: str, seed: int) -> None:
    """A family lies wholly in one partition: refuse a seed from the other one."""
    expected = family_partition(family)
    actual = partition_for_seed(seed)
    if actual != expected:
        raise ProtocolRefusalError(
            f"{family} lies in {expected}, but seed {seed} is in {actual}; "
            "a family lies wholly in one partition"
        )
