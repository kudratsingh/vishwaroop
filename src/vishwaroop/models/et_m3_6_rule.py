"""ET-M3-6's frozen scoring arithmetic, with no torch and no data (``evals/M3-exit-tests.json``).

Tables are plain mappings: ``table[seed][stream]`` is a list of 10 RMSEs, horizons 1 to 10, in the
stream's own units (joint_position in rad, object_position in m). Every function refuses a missing
seed, stream or horizon rather than comparing what is there.

- Helps rule: Fk helps when (a) for every seed in {0, 1, 2}, horizon 1 to 10 and both streams,
  RMSE(Fk) < RMSE(F1) strictly on the evaluation family, values equal to 6 significant figures
  counting as not below; and (b) W(Fk) >= W(F0) - 0.02, W being the minimum over seeds, horizons
  and both streams of 1 - RMSE_model / RMSE of the lowest of the five baselines, on the 23 no-harm
  episodes.
- Gap fraction: (F0 - Fk) / (F0 - F_star) per stream and seed at horizons 1 and 10, ``undefined``
  where F0 - F_star <= 0.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

SEEDS = ("0", "1", "2")
STREAMS = ("joint_position", "object_position")
HORIZONS = 10
MARGIN = 0.02
SIGNIFICANT_FIGURES = 6
GAP_HORIZONS = (1, 10)
UNDEFINED = "undefined"
REFERENCE = "F1"
NO_HELP_FROM_TARGET_DATA = "the rule could not detect help even from collected target data"
Table = Mapping[str, Mapping[str, Sequence[float]]]


class RuleInputError(ValueError):
    """A table without every seed, stream and horizon the rule reads."""


def check_table(table: Table, name: str) -> None:
    for seed in SEEDS:
        if seed not in table:
            raise RuleInputError(f"{name} has no seed {seed}")
        for stream in STREAMS:
            values = table[seed].get(stream)
            if values is None or len(values) != HORIZONS:
                raise RuleInputError(f"{name} seed {seed} {stream} is not {HORIZONS} horizons")


def same_to_six_figures(a: float, b: float) -> bool:
    """Whether two values are equal when each is rounded to 6 significant figures."""
    digits = SIGNIFICANT_FIGURES - 1
    return f"{a:.{digits}e}" == f"{b:.{digits}e}"


def strictly_below(a: float, b: float) -> bool:
    """``a < b``, where values equal to 6 significant figures count as not below."""
    return a < b and not same_to_six_figures(a, b)


def lowest_baseline(
    baselines: Mapping[str, Mapping[str, Sequence[float]]], stream: str
) -> list[float]:
    """The lowest of the baselines' RMSEs at each horizon, for one stream."""
    if len(baselines) != 5:
        raise RuleInputError(f"{len(baselines)} baselines, not the five")
    for name, streams in baselines.items():
        if len(streams.get(stream, ())) != HORIZONS:
            raise RuleInputError(f"baseline {name} {stream} is not {HORIZONS} horizons")
    return [min(streams[stream][h] for streams in baselines.values()) for h in range(HORIZONS)]


def worst_reduction(
    no_harm: Table, baselines: Mapping[str, Mapping[str, Sequence[float]]]
) -> dict[str, Any]:
    """W: the minimum over seeds, horizons and both streams of 1 - RMSE_model / lowest baseline,
    on the no-harm episodes, and where it falls."""
    check_table(no_harm, "no-harm table")
    worst: dict[str, Any] = {"value": float("inf")}
    for seed in SEEDS:
        for stream in STREAMS:
            lowest = lowest_baseline(baselines, stream)
            for h in range(HORIZONS):
                value = 1.0 - no_harm[seed][stream][h] / lowest[h]
                if value < worst["value"]:
                    worst = {"value": value, "seed": seed, "stream": stream, "horizon": h + 1}
    return worst


def helps(
    arm: Table, reference: Table, w_arm: float, w_f0: float, name: str = "Fk"
) -> dict[str, Any]:
    """The frozen helps rule for one arm against a reference arm (F1 for the threshold)."""
    check_table(arm, name)
    check_table(reference, "reference")
    not_below = [
        {"seed": seed, "stream": stream, "horizon": h + 1, "arm": a, "reference": b}
        for seed in SEEDS
        for stream in STREAMS
        for h, (a, b) in enumerate(zip(arm[seed][stream], reference[seed][stream], strict=True))
        if not strictly_below(a, b)
    ]
    part_a = not not_below
    part_b = w_arm >= w_f0 - MARGIN
    return {
        "helps": part_a and part_b,
        "a_below_reference_everywhere": part_a,
        "a_cells_not_below": not_below,
        "b_no_harm": part_b,
        "w_arm": w_arm,
        "w_f0": w_f0,
        "w_f0_minus_margin": w_f0 - MARGIN,
    }


def differences(reference: Table, arm: Table) -> dict[str, dict[str, list[float]]]:
    """Per seed and stream, F1 - Fk at every horizon."""
    check_table(reference, "reference")
    check_table(arm, "arm")
    return {
        seed: {
            stream: [b - a for a, b in zip(arm[seed][stream], reference[seed][stream], strict=True)]
            for stream in STREAMS
        }
        for seed in SEEDS
    }


def gap_fraction(f0: Table, arm: Table, f_star: Table) -> dict[str, dict[str, dict[str, Any]]]:
    """(F0 - Fk) / (F0 - F_star) per seed and stream at horizons 1 and 10, ``undefined`` where
    F0 - F_star <= 0."""
    for table, name in ((f0, "F0"), (arm, "arm"), (f_star, "F_star")):
        check_table(table, name)
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for seed in SEEDS:
        out[seed] = {}
        for stream in STREAMS:
            out[seed][stream] = {}
            for horizon in GAP_HORIZONS:
                h = horizon - 1
                gap = f0[seed][stream][h] - f_star[seed][stream][h]
                closed = f0[seed][stream][h] - arm[seed][stream][h]
                out[seed][stream][f"h{horizon}"] = UNDEFINED if gap <= 0 else closed / gap
    return out


def score(
    evaluation: Mapping[str, Table],
    no_harm: Mapping[str, Table],
    baselines_no_harm: Mapping[str, Mapping[str, Sequence[float]]],
) -> dict[str, Any]:
    """Every frozen comparison among the arms present. ``evaluation`` and ``no_harm`` map an arm to
    its table. F3 is out of WO-022's scope, so ET-M3-6's threshold is not decided here."""
    for required in ("F0", "F_star", REFERENCE):
        if required not in evaluation or required not in no_harm:
            raise RuleInputError(f"arm {required} is required")
    w = {arm: worst_reduction(no_harm[arm], baselines_no_harm) for arm in no_harm}
    w_f0 = w["F0"]["value"]

    def rule(arm: str, reference: str) -> dict[str, Any]:
        return helps(evaluation[arm], evaluation[reference], w[arm]["value"], w_f0, arm)

    comparisons: dict[str, Any] = {"F_star_vs_F1": rule("F_star", REFERENCE)}
    if "F2" in evaluation:
        comparisons["F2_vs_F1"] = rule("F2", REFERENCE)
        if "F1s" in evaluation:
            comparisons["F2_vs_F1s"] = rule("F2", "F1s")
    if "F3" in evaluation:
        comparisons["F3_vs_F1"] = rule("F3", REFERENCE)
    others = [arm for arm in evaluation if arm != REFERENCE]
    return {
        "w": w,
        "comparisons": comparisons,
        "differences_f1_minus_fk": {
            arm: differences(evaluation[REFERENCE], evaluation[arm]) for arm in others
        },
        "gap_fraction_closed": {
            arm: gap_fraction(evaluation["F0"], evaluation[arm], evaluation["F_star"])
            for arm in evaluation
            if arm not in ("F0", "F_star")
        },
        "sensitivity": (
            "F_star helps by the rule against F1"
            if comparisons["F_star_vs_F1"]["helps"]
            else NO_HELP_FROM_TARGET_DATA
        ),
        "et_m3_6": (
            ("passed" if comparisons["F3_vs_F1"]["helps"] else "failed")
            if "F3_vs_F1" in comparisons
            else "not decided: F3 is out of WO-022's scope"
        ),
    }
