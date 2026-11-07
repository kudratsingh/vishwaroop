"""ET-M3-1's checker rules, tolerance pilot, threshold and one-shot refusals, on FABRICATED
measurements. Standard library only, so these run on the CPU tier."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from vishwaroop.synth.checker import (
    MASK_RULES,
    FrameStats,
    PilotCandidate,
    PilotStopError,
    Tolerances,
    credited,
    cube_area,
    evaluate,
    load_tolerances,
    merge_distance,
    pilot_tolerances,
    reference,
    verdict,
    wilson,
)
from vishwaroop.synth.et_m3_1 import check_frozen, check_not_run, check_recorded

ROOT = Path(__file__).resolve().parents[1]
SHAPE = (512, 512, 3)
CUBE = FrameStats(red=((600, 300.0, 200.0),), green_count=400, green_centroid=(150.0, 350.0))


def snapshot_manifest(seed: int = 10000) -> dict[str, Any]:
    return {
        "task_id": "PickCubeSO100-v1",
        "task_version": "m0-1",
        "seed": seed,
        "asset_sha256s": ["a" * 64, "b" * 64],
        "cube_half_size_m": 0.0125,
        "cube_colour": "red",
        "goal_position": [-0.46, 0.0, 0.05],
        "camera": {"exposed": False},
    }


def tolerances(**changes: Any) -> Tolerances:
    values: dict[str, Any] = {
        "a_lo": 0.8,
        "a_hi": 1.25,
        "merge_radius_px": 20.0,
        "first_frame_tolerance": 0.5,
        "goal_centroid_px": 3.0,
        "min_green_pixels": 100,
    }
    values.update(changes)
    return Tolerances(**values)


def frame(red: tuple[tuple[int, float, float], ...], green: int = 400, at: float = 350.0) -> Any:
    return FrameStats(red=red, green_count=green, green_centroid=(150.0, at) if green else None)


def run_evaluate(
    frames: list[FrameStats],
    manifest: dict[str, Any] | None = None,
    first: float = 0.0,
    tol: Tolerances | None = None,
) -> Any:
    tol = tol or tolerances()
    snap = snapshot_manifest()
    ref = reference(snap, CUBE, SHAPE, tol)
    candidate = manifest or {key: snap[key] for key in ref.manifest}
    return evaluate(candidate, [SHAPE] * len(frames), first, frames, ref, tol)


def test_merged_area_counts_components_within_the_radius_of_the_largest() -> None:
    stats = frame(((500, 300.0, 200.0), (80, 300.0, 215.0), (200, 300.0, 260.0)))
    assert cube_area(stats, 20.0) == (580, 200)
    assert cube_area(stats, 60.0) == (780, 0)
    assert merge_distance(stats) == 60.0
    assert cube_area(frame(()), 20.0) == (0, 0)
    assert merge_distance(CUBE) == 0.0


def test_an_unmodified_candidate_passes() -> None:
    frames = [CUBE, frame(((560, 301.0, 205.0), (40, 301.0, 215.0))), frame(((610, 302.0, 210.0),))]
    result = run_evaluate(frames)
    assert result.passed, result.to_json()


def test_each_check_rejects_its_own_mismatch() -> None:
    snap = snapshot_manifest()
    wrong = {key: snap[key] for key in ("task_id", "task_version", "seed", "asset_sha256s")}
    wrong.update(cube_half_size_m=0.0125, cube_colour="red", goal_position=[-0.43, 0.0, 0.05])
    assert run_evaluate([CUBE], manifest=wrong).to_json()["failed_checks"] == ["manifest"]
    assert run_evaluate([CUBE], first=0.6).to_json()["failed_checks"] == ["first_frame"]
    gone = run_evaluate([CUBE, frame(())])
    assert gone.to_json()["failed_checks"] == ["cube_area"]
    assert gone.failed["cube_area"]["frame"] == 1
    small = run_evaluate([frame(((360, 300.0, 200.0),))])
    assert small.to_json()["failed_checks"] == ["cube_area"]
    big = run_evaluate([frame(((1536, 300.0, 200.0),))])
    assert big.to_json()["failed_checks"] == ["cube_area"]
    twice = run_evaluate([frame(((600, 300.0, 200.0), (600, 300.0, 260.0)))])
    assert twice.to_json()["failed_checks"] == ["extra_red"]
    moved = run_evaluate([frame(((600, 300.0, 200.0),), at=360.0)])
    assert moved.to_json()["failed_checks"] == ["goal_centroid"]


def test_a_small_red_speck_or_a_hidden_goal_is_not_a_failure() -> None:
    speck = frame(((600, 300.0, 200.0), (149, 50.0, 50.0)))
    assert run_evaluate([speck]).passed
    hidden = frame(((600, 300.0, 200.0),), green=99, at=500.0)
    assert run_evaluate([hidden]).passed


def test_band_ends_are_inside_the_band() -> None:
    assert run_evaluate([frame(((480, 300.0, 200.0),))]).passed
    assert run_evaluate([frame(((750, 300.0, 200.0),))]).passed


def pilot(*ratios: float, merge: float = 10.0, green: int = 300, goal: float = 2.0) -> list[Any]:
    """Two pilot candidates whose frames show the cube at the given area ratios."""
    snapshot = FrameStats(((1000, 300.0, 200.0),), 400, (150.0, 350.0))
    frames = [FrameStats(((1000, 300.0, 200.0),), 400, (150.0, 350.0))]
    frames += [
        FrameStats(
            ((round(1000 * r) - 100, 300.0, 200.0), (100, 300.0, 200.0 + merge)),
            green,
            (150.0, 350.0 + goal),
        )
        for r in ratios
    ]
    return [
        PilotCandidate(10900, snapshot, tuple(frames), 0.2),
        PilotCandidate(10901, snapshot, tuple(frames[:1]), 0.4),
    ]


def test_the_pilot_widens_each_observed_extreme_by_ten_percent() -> None:
    result = pilot_tolerances(pilot(0.7, 1.2, merge=10.0, green=300, goal=2.0))
    assert result["merge_radius_px"] == pytest.approx(11.0)
    assert result["cube_area_band"] == pytest.approx([0.63, 1.32])
    assert result["goal_centroid_px"] == pytest.approx(2.2)
    assert result["first_frame_tolerance"] == pytest.approx(0.44)
    assert result["min_green_pixels"] == 300
    assert result["masks"] == MASK_RULES
    assert result["observed"]["area_ratio_min"] == {"value": 0.7, "seed": 10900, "frame": 1}
    tol = Tolerances.from_json(result)
    assert (tol.a_lo, tol.a_hi) == pytest.approx((0.63, 1.32))


@pytest.mark.parametrize("ratios", [(0.3, 1.0), (1.0, 2.33), (0.39, 2.4)])
def test_the_pilot_stops_when_the_band_leaves_the_frozen_limits(ratios: tuple[float, ...]) -> None:
    with pytest.raises(PilotStopError, match=r"tell|0\.36") as stop:
        pilot_tolerances(pilot(*ratios))
    assert "band" in stop.value.observed


def test_the_pilot_just_inside_the_limits_is_kept() -> None:
    result = pilot_tolerances(pilot(0.401, 2.32))
    low, high = result["cube_area_band"]
    assert low > 0.36 and high < 2.56


def test_the_pilot_stops_when_a_snapshot_shows_no_cube() -> None:
    empty = FrameStats((), 400, (150.0, 350.0))
    with pytest.raises(PilotStopError, match="no cube"):
        pilot_tolerances([PilotCandidate(10900, empty, (CUBE,), 0.0)])


def test_the_injection_credit_rule() -> None:
    assert credited(True, False)
    assert not credited(True, True)
    assert not credited(False, False)
    assert not credited(False, True)
    assert not credited(True, None)


def controls(false: int) -> list[dict[str, Any]]:
    return [
        {"seed": 10000 + n, "passed": n >= false, "failed_checks": [] if n >= false else ["x"]}
        for n in range(60)
    ]


def injections(**overrides: Any) -> list[dict[str, Any]]:
    items = []
    for n in range(60):
        item = {
            "type": 1 + n // 10,
            "name": f"type-{1 + n // 10}",
            "seed": 10100 + n,
            "source_passed": True,
            "injected_passed": False,
            "failed_checks": ["cube_area"],
        }
        if n == 0:
            item.update(overrides)
        items.append(item)
    return items


def test_the_threshold_passes_with_all_rejected_and_three_false_rejections() -> None:
    result = verdict(controls(3), injections())
    assert result["passed"]
    assert result["injections_rejected"] == 60
    assert result["false_rejections"] == 3
    assert result["rejections_by_check"] == {"cube_area": 60}
    low, high = result["false_rejection_wilson95"]
    assert low < 0.05 < high
    assert "physics renders" in result["statement"]


def test_the_threshold_fails_on_a_fourth_false_rejection() -> None:
    assert not verdict(controls(4), injections())["passed"]


@pytest.mark.parametrize(
    "overrides",
    [{"injected_passed": True}, {"source_passed": False}, {"injected_passed": None}],
)
def test_one_uncredited_injection_fails_the_threshold(overrides: dict[str, Any]) -> None:
    result = verdict(controls(0), injections(**overrides))
    assert not result["passed"]
    assert result["injections_rejected"] == 59
    assert result["injections_not_credited"][0]["seed"] == 10100


def test_too_few_injections_or_controls_fail_the_threshold() -> None:
    assert not verdict(controls(0), injections()[:59])["passed"]
    assert not verdict(controls(0)[:59], injections())["passed"]


def test_wilson_matches_a_known_interval() -> None:
    low, high = wilson(3, 60)
    assert low == pytest.approx(0.01713, abs=1e-4)
    assert high == pytest.approx(0.13701, abs=1e-4)


def tolerance_file(tmp_path: Path, **changes: Any) -> tuple[Path, str]:
    data = pilot_tolerances(pilot(0.7, 1.2))
    data.update(changes)
    path = tmp_path / "M3-checker-tolerances.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_tolerances_load_only_with_their_pinned_sha256(tmp_path: Path) -> None:
    path, digest = tolerance_file(tmp_path)
    assert load_tolerances(path, digest).merge_radius_px == pytest.approx(11.0)
    with pytest.raises(ValueError, match="pinned"):
        load_tolerances(path, "0" * 64)


@pytest.mark.parametrize(
    ("changes", "match"),
    [
        ({"masks": {**MASK_RULES, "connectivity": 4}}, "mask rules"),
        ({"cube_area_band": [0.3, 1.2]}, "limits"),
        ({"cube_area_band": [0.7, 2.6]}, "limits"),
        ({"protocol_version": "m3-protocol-2"}, "protocol"),
        ({"other_component_fraction": 0.3}, "0.25"),
    ],
)
def test_tolerances_off_the_frozen_rules_are_refused(
    tmp_path: Path, changes: dict[str, Any], match: str
) -> None:
    path, digest = tolerance_file(tmp_path, **changes)
    with pytest.raises(ValueError, match=match):
        load_tolerances(path, digest)


def test_a_second_pilot_or_scoring_is_refused(tmp_path: Path) -> None:
    for name in ("et_m3_1_pilot.json", "et_m3_1_score.json"):
        check_not_run(tmp_path, name)
        run = tmp_path / f"run-{name}"
        run.mkdir()
        (run / f"{name}.partial").write_text("{}", encoding="utf-8")
        with pytest.raises(ValueError, match="allows one"):
            check_not_run(tmp_path, name)


def test_scoring_needs_the_tolerances_sha256_in_the_status_ledger(tmp_path: Path) -> None:
    ledger = tmp_path / "STATUS.jsonl"
    digest = "ab" * 32
    ledger.write_text(json.dumps({"note": f"something else sha256 {digest}"}) + "\n")
    with pytest.raises(ValueError, match="not recorded"):
        check_recorded(digest, ledger)
    with ledger.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"note": f"evals/M3-checker-tolerances.json sha256 {digest}"}))
    check_recorded(digest, ledger)
    with pytest.raises(ValueError, match="not recorded"):
        check_recorded("cd" * 32, ledger)


def test_the_frozen_m3_files_are_the_ones_the_commands_pin(tmp_path: Path) -> None:
    pinned = check_frozen(
        {
            ROOT / "evals/M3-exit-tests.json": (
                "2e35a50397b1c97919cb0be7d31b09b374d3fd0f0564741090b93c5e31e8f2d4"
            ),
            ROOT / "evals/M3-protocol.md": (
                "34ac1338b97d732f3de66f30e83227778af5360117df7674b21dce7dc253ea34"
            ),
        }
    )
    assert len(pinned) == 2
    changed = tmp_path / "M3-exit-tests.json"
    changed.write_bytes((ROOT / "evals/M3-exit-tests.json").read_bytes() + b" ")
    with pytest.raises(ValueError, match="frozen"):
        check_frozen({changed: "2e35a50397b1c97919cb0be7d31b09b374d3fd0f0564741090b93c5e31e8f2d4"})
