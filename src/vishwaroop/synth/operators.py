"""M3's two failure operators and ET-M3-1's episode kinds (``evals/M3-exit-tests.json``).

Each operator is a ``PlanSettings`` for the scripted controller, drawn by ET-M3-6.F2's rule from
``random.Random(seed).uniform``, with every other setting at its default:

- ``m3-synth-lateral-miss``: ``grasp_offset_xy_m = (0.0, s * d)``, ``d`` in [0.02, 0.05] m, and
  ``s = +1`` for the 1st, 3rd, 5th lateral-miss episode of a sequence, ``-1`` for the 2nd, 4th, 6th.
- ``m3-synth-close-high``: ``grasp_height_m = 0.012 + d``, ``d`` in [0.02, 0.04] m.

ET-M3-1's candidates use the nominal scripted demo on even seeds and an operator episode on odd
seeds, lateral-miss and close-high alternating by seed (seed mod 4 is 1 for lateral-miss, 3 for
close-high). Leak rule 1 (``evals/M3-protocol.md`` section 2a) refuses an operator setting equal to
a ``VARIANTS`` family's, or to M1's branch chunks; ``check_leak_rule_1`` enforces it on every
setting this module returns.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass, fields

from ..sim.baseline import VARIANTS, PlanSettings
from ..sim.branches import CHUNK, OFFSETS_RAD
from .protocol import family_id

LATERAL_MISS = "lateral-miss"
CLOSE_HIGH = "close-high"
NOMINAL = "nominal"
OPERATORS = (LATERAL_MISS, CLOSE_HIGH)
LATERAL_MISS_RANGE_M = (0.02, 0.05)
CLOSE_HIGH_RANGE_M = (0.02, 0.04)
DEFAULT_GRASP_HEIGHT_M = 0.012
# M1's branch chunks (sim/branches.py): constant arm offsets of these spreads, and a gripper
# inversion over CHUNK steps. No PlanSettings field inverts the gripper; arm noise is the field
# that could reproduce an arm offset of the same size.
BRANCH_ARM_OFFSETS_RAD = OFFSETS_RAD
BRANCH_INVERSION_STEPS = CHUNK
_DEFAULT = PlanSettings()
_ABSENT = object()


class LeakRuleError(ValueError):
    """An operator setting reproduces an existing family's, or an M1 branch chunk (leak rule 1)."""


def _draw(seed: int, low: float, high: float) -> float:
    return random.Random(seed).uniform(low, high)  # noqa: S311 - frozen draw, not cryptography


def lateral_sign(k: int) -> int:
    """``+1`` for the 1st, 3rd, 5th lateral-miss episode, ``-1`` for the 2nd, 4th, 6th."""
    if k < 1:
        raise ValueError(f"the lateral-miss episode count starts at 1, not {k}")
    return 1 if k % 2 == 1 else -1


def lateral_miss(seed: int, k: int) -> PlanSettings:
    """``m3-synth-lateral-miss`` on ``seed``, as the ``k``-th lateral-miss episode (from 1)."""
    d = _draw(seed, *LATERAL_MISS_RANGE_M)
    settings = PlanSettings(grasp_offset_xy_m=(0.0, lateral_sign(k) * d))
    check_leak_rule_1(settings)
    return settings


def close_high(seed: int) -> PlanSettings:
    """``m3-synth-close-high`` on ``seed``: the gripper closes ``d`` above the grasp height."""
    d = _draw(seed, *CLOSE_HIGH_RANGE_M)
    settings = PlanSettings(grasp_height_m=DEFAULT_GRASP_HEIGHT_M + d)
    check_leak_rule_1(settings)
    return settings


def _changed(settings: PlanSettings) -> dict[str, object]:
    return {
        field.name: getattr(settings, field.name)
        for field in fields(PlanSettings)
        if getattr(settings, field.name) != getattr(_DEFAULT, field.name)
    }


def check_leak_rule_1(settings: PlanSettings) -> None:
    """Refuse a setting that reproduces a ``VARIANTS`` family or an M1 branch chunk.

    Refused: settings equal to any family's (the nominal included), any changed field equal to the
    value a family changes it to (for example a grasp offset of (-0.04, 0)), and arm noise equal to
    a branch chunk's arm offset (0.05 or 0.15 rad).
    """
    changed = _changed(settings)
    for name, family in VARIANTS.items():
        if settings == family:
            raise LeakRuleError(f"settings equal family {name}'s: {settings}")
        for field, value in _changed(family).items():
            if changed.get(field, _ABSENT) == value:
                raise LeakRuleError(f"{field} = {value!r} reproduces family {name}")
    if settings.arm_noise_rad in BRANCH_ARM_OFFSETS_RAD:
        raise LeakRuleError(
            f"arm noise {settings.arm_noise_rad} rad reproduces an M1 branch chunk's arm offset"
        )


@dataclass(frozen=True)
class EpisodeKind:
    """One ET-M3-1 candidate's episode: what runs on ``seed`` and with which settings.

    ``kind`` is ``nominal`` or an operator name; ``family`` is ``nominal`` or the operator's
    ``m3-synth-`` id; ``k`` is the lateral-miss count in its sequence, or ``None``.
    """

    seed: int
    kind: str
    family: str
    settings: PlanSettings
    k: int | None = None

    def to_json(self) -> dict[str, object]:
        return {
            "seed": self.seed,
            "kind": self.kind,
            "family": self.family,
            "k": self.k,
            "grasp_offset_xy_m": list(self.settings.grasp_offset_xy_m),
            "grasp_height_m": self.settings.grasp_height_m,
            "noise_seed": self.seed,
        }


def kind_for_seed(seed: int) -> str:
    """Even seeds nominal; odd seeds lateral-miss (seed mod 4 = 1) or close-high (mod 4 = 3)."""
    if seed % 2 == 0:
        return NOMINAL
    return LATERAL_MISS if seed % 4 == 1 else CLOSE_HIGH


def et_m3_1_episodes(seeds: Sequence[int]) -> list[EpisodeKind]:
    """The episode for each seed of one sequence, in ascending seed order.

    The lateral-miss sign counts lateral-miss episodes within this sequence, so each of the pilot,
    the controls and the injection sources is its own sequence.
    """
    if list(seeds) != sorted(set(seeds)):
        raise ValueError("an ET-M3-1 sequence is distinct seeds in ascending order")
    episodes = []
    lateral = 0
    for seed in seeds:
        kind = kind_for_seed(seed)
        if kind == NOMINAL:
            episodes.append(EpisodeKind(seed, NOMINAL, NOMINAL, VARIANTS[NOMINAL]))
        elif kind == LATERAL_MISS:
            lateral += 1
            settings = lateral_miss(seed, lateral)
            episodes.append(EpisodeKind(seed, kind, family_id("synth", kind), settings, k=lateral))
        else:
            episodes.append(EpisodeKind(seed, kind, family_id("synth", kind), close_high(seed)))
    return episodes
