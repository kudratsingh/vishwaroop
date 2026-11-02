"""The verdict arithmetic for ET-M1-1 and ET-M1-3, with no torch and no data.

Kept apart from the evaluator so the frozen rules are testable on fabricated numbers. Every function
works on plain lists, and refuses mismatched lengths rather than comparing what is there.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence

HORIZONS = 10
MIN_REDUCTION = 0.2
MIN_SPEARMAN = 0.5
NOMINAL_COVERAGE = 0.9
COVERAGE_TOLERANCE = 0.10
MIN_DEV_EPISODES = 200
REQUIRED_STREAMS = ("joint_position", "object_position")


def lowest_baseline(baselines: Mapping[str, Sequence[float]]) -> list[float]:
    """The lowest baseline RMSE at each horizon."""
    if not baselines:
        raise ValueError("no baselines")
    for name, values in baselines.items():
        if len(values) != HORIZONS:
            raise ValueError(f"baseline {name} has {len(values)} horizons, not {HORIZONS}")
    return [min(values[h] for values in baselines.values()) for h in range(HORIZONS)]


def reductions_at_each_horizon(
    learned: Sequence[float], baselines: Mapping[str, Sequence[float]]
) -> list[float]:
    """One minus learned over lowest baseline, for each horizon."""
    if len(learned) != HORIZONS:
        raise ValueError(f"learned has {len(learned)} horizons, not {HORIZONS}")
    return [1.0 - a / b for a, b in zip(learned, lowest_baseline(baselines), strict=True)]


def et_m1_1_passes(
    by_seed: Mapping[str, Mapping[str, Sequence[float]]],
    episodes: int,
) -> bool:
    """Every seed, every required stream and every horizon reach the threshold, on enough episodes.

    ``by_seed`` maps a seed to a stream's reductions. A missing stream is an error, not a pass.
    """
    if episodes < MIN_DEV_EPISODES:
        raise ValueError(f"{episodes} dev episodes, and ET-M1-1 requires {MIN_DEV_EPISODES}")
    if not by_seed:
        raise ValueError("no seeds to judge")
    for seed, streams in by_seed.items():
        for stream in REQUIRED_STREAMS:
            if stream not in streams:
                raise ValueError(f"seed {seed} has no {stream}")
            if len(streams[stream]) != HORIZONS:
                raise ValueError(f"seed {seed} {stream} is not {HORIZONS} horizons")
            if not all(value >= MIN_REDUCTION for value in streams[stream]):
                return False
    return True


def et_m1_3_passes(
    by_seed: Mapping[str, Mapping[str, Mapping[str, Sequence[float]]]],
    episodes: int,
) -> bool:
    """Spearman and calibrated coverage hold on every seed, required stream and horizon."""
    if episodes < MIN_DEV_EPISODES:
        raise ValueError(f"{episodes} dev episodes, and ET-M1-3 requires {MIN_DEV_EPISODES}")
    if not by_seed:
        raise ValueError("no seeds to judge")
    for seed, streams in by_seed.items():
        for stream in REQUIRED_STREAMS:
            if stream not in streams:
                raise ValueError(f"seed {seed} has no {stream}")
            spearman = streams[stream]["spearman"]
            coverage = streams[stream]["calibrated_coverage"]
            if len(spearman) != HORIZONS or len(coverage) != HORIZONS:
                raise ValueError(f"seed {seed} {stream} is not {HORIZONS} horizons")
            if not all(value >= MIN_SPEARMAN for value in spearman):
                return False
            if not all(abs(value - NOMINAL_COVERAGE) <= COVERAGE_TOLERANCE for value in coverage):
                return False
    return True


def conformal_scale(ratios: Sequence[float], level: float = NOMINAL_COVERAGE) -> float:
    """The scale on predicted std that covers ``level`` of the calibration errors.

    ``ratios`` are absolute error over predicted std, and the rank is the split-conformal one, which
    rounds up. Non-finite ratios are refused.
    """
    if not ratios:
        raise ValueError("no calibration values")
    if not all(math.isfinite(value) for value in ratios):
        raise ValueError("a calibration value is not finite")
    ordered = sorted(ratios)
    rank = min(math.ceil((len(ordered) + 1) * level), len(ordered))
    return ordered[rank - 1]


def bootstrap_interval(
    squared_by_episode: Sequence[float],
    count_by_episode: Sequence[int],
    baselines_by_episode: Mapping[str, Sequence[float]],
    seed: int = 0,
    resamples: int = 2000,
) -> tuple[float, float]:
    """A 95% interval on the reduction at one horizon, resampling whole episodes.

    Windows in one episode are not independent, so episodes are what gets resampled. Each resample
    finds its own lowest baseline.
    """
    size = len(squared_by_episode)
    if size == 0 or size != len(count_by_episode):
        raise ValueError("episode lists are empty or differ in length")
    if any(len(values) != size for values in baselines_by_episode.values()):
        raise ValueError("a baseline covers different episodes")
    chooser = random.Random(seed)  # noqa: S311 - a reproducible resample, not a secret
    results = []
    for _ in range(resamples):
        chosen = chooser.choices(range(size), k=size)
        windows = sum(count_by_episode[item] for item in chosen)
        learned = math.sqrt(sum(squared_by_episode[item] for item in chosen) / windows)
        lowest = min(
            math.sqrt(sum(values[item] for item in chosen) / windows)
            for values in baselines_by_episode.values()
        )
        results.append(1.0 - learned / lowest)
    results.sort()
    return results[int(0.025 * resamples)], results[int(0.975 * resamples) - 1]
