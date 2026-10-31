"""The independent place rubric. All inputs here are FABRICATED, not measured episodes."""

from __future__ import annotations

import ast
import hashlib
import json
import math
import sys
from pathlib import Path

import pytest

from vishwaroop.interfaces import SuccessJudge
from vishwaroop.outcome.pickplace import (
    PickPlaceJudge,
    PlaceRubric,
    StateSample,
    assess,
    samples_from_records,
)

RUBRIC = PlaceRubric(
    rubric_version="test",
    target_radius_m=0.015625,
    rest_height_m=0.0125,
    rest_height_tolerance_m=0.005,
    min_lift_above_rest_m=0.02,
    max_step_motion_m=0.001,
    dwell_steps=10,
)
TARGET = (0.1, 0.0, 0.0125)
REST = (0.1, 0.0, 0.0125)
DWELL = RUBRIC.dwell_steps


def _samples(
    final: tuple[float, float, float] = REST,
    *,
    lifted: bool = True,
    grasped_at_end: bool = False,
    dwell: int = DWELL + 1,
    target: tuple[float, float, float] = TARGET,
) -> list[StateSample]:
    """A lift, then ``dwell`` samples at ``final``. Eleven samples hold the last ten steps."""
    height = 0.08 if lifted else 0.0125
    path = [(0.0, 0.0, 0.0125), (0.05, 0.0, height), (0.1, 0.0, height)]
    samples = [StateSample(i, p, target, True) for i, p in enumerate(path)]
    start = len(samples)
    samples += [StateSample(start + i, final, target, grasped_at_end) for i in range(dwell)]
    return samples


def _with(samples: list[StateSample], index: int, **changes: object) -> list[StateSample]:
    old = samples[index]
    fields = {
        "step": old.step,
        "object_position_m": old.object_position_m,
        "target_position_m": old.target_position_m,
        "grasped": old.grasped,
    }
    fields.update(changes)
    result = list(samples)
    result[index] = StateSample(**fields)  # type: ignore[arg-type]
    return result


def test_success() -> None:
    outcome = assess(_samples(), RUBRIC)
    assert (outcome.success, outcome.label) == (True, "success")
    assert outcome.rubric_version == "test"
    assert outcome.samples == 3 + DWELL + 1


def test_never_lifted_is_a_failure_even_when_pushed_into_the_target() -> None:
    outcome = assess(_samples(lifted=False), RUBRIC)
    assert (outcome.success, outcome.label) == (False, "never_lifted")


@pytest.mark.parametrize(
    ("height", "lifted"),
    [(0.0125 + 0.0201, True), (0.0125 + 0.0199, False)],
)
def test_lift_boundary(height: float, lifted: bool) -> None:
    samples = _with(_samples(), 1, object_position_m=(0.05, 0.0, height))
    samples = _with(samples, 2, object_position_m=(0.1, 0.0, 0.0125))
    assert (assess(samples, RUBRIC).label == "never_lifted") is not lifted


def test_a_lift_outside_the_window_counts() -> None:
    assert assess(_samples(dwell=50), RUBRIC).success is True


@pytest.mark.parametrize("offset", [-1, -5, -DWELL])
def test_grasped_at_any_step_of_the_window_fails(offset: int) -> None:
    samples = _with(_samples(), offset, grasped=True)
    assert assess(samples, RUBRIC).label == "still_grasped"


def test_grasped_just_before_the_window_passes() -> None:
    samples = _with(_samples(), -DWELL - 1, grasped=True)
    assert assess(samples, RUBRIC).success is True


@pytest.mark.parametrize("offset", [-1, -5, -DWELL])
def test_off_the_table_at_any_step_of_the_window_fails(offset: int) -> None:
    samples = _with(_samples(), offset, object_position_m=(0.1, 0.0, 0.05))
    assert assess(samples, RUBRIC).label == "not_on_table"


@pytest.mark.parametrize("offset", [-1, -5, -DWELL])
def test_outside_the_target_at_any_step_of_the_window_fails(offset: int) -> None:
    samples = _with(_samples(), offset, object_position_m=(0.2, 0.0, 0.0125))
    assert assess(samples, RUBRIC).label == "outside_target"


def test_held_in_the_air_over_the_target_fails() -> None:
    outcome = assess(_samples((0.1, 0.0, 0.05)), RUBRIC)
    assert (outcome.success, outcome.label) == (False, "not_on_table")


def test_below_the_table_fails() -> None:
    assert assess(_samples((0.1, 0.0, 0.0125 - 0.006)), RUBRIC).label == "not_on_table"


@pytest.mark.parametrize(
    ("height", "ok"), [(0.017, True), (0.018, False), (0.008, True), (0.007, False)]
)
def test_table_height_boundaries(height: float, ok: bool) -> None:
    assert (assess(_samples((0.1, 0.0, height)), RUBRIC).success is True) is ok


def test_outside_target_fails() -> None:
    outcome = assess(_samples((0.2, 0.0, 0.0125)), RUBRIC)
    assert (outcome.success, outcome.label) == (False, "outside_target")


def test_a_miss_in_y_alone_fails() -> None:
    assert assess(_samples((0.1, 0.02, 0.0125)), RUBRIC).label == "outside_target"


def test_target_distance_is_in_the_plane() -> None:
    high_goal = (TARGET[0], TARGET[1], 0.09)
    assert assess(_samples(target=high_goal), RUBRIC).success is True


def test_exactly_on_the_radius_passes_and_just_outside_fails() -> None:
    on_edge = (TARGET[0] + RUBRIC.target_radius_m, 0.0, 0.0125)
    assert assess(_samples(on_edge), RUBRIC).success is True
    outside = (TARGET[0] + RUBRIC.target_radius_m + 1e-6, 0.0, 0.0125)
    assert assess(_samples(outside), RUBRIC).label == "outside_target"


@pytest.mark.parametrize("offset", [-1, -5])
def test_still_moving_late_in_the_window_fails(offset: int) -> None:
    samples = _with(_samples(), offset, object_position_m=(0.1 + 0.002, 0.0, 0.0125))
    outcome = assess(samples, RUBRIC)
    assert (outcome.success, outcome.label) == (False, "not_settled")


def test_motion_during_the_first_step_of_the_window_fails() -> None:
    """Ten steps are eleven samples, so the motion into the window's first sample counts."""
    samples = _with(_samples(), -DWELL - 1, object_position_m=(0.1 + 0.01, 0.0, 0.0125))
    assert assess(samples, RUBRIC).label == "not_settled"


def test_motion_before_the_ten_steps_passes() -> None:
    samples = _with(_samples(dwell=DWELL + 2), -DWELL - 2, object_position_m=(0.11, 0.0, 0.0125))
    assert assess(samples, RUBRIC).success is True


@pytest.mark.parametrize(
    ("position", "settled"),
    [((0.1, 0.0, 0.0125 + 0.0009), True), ((0.1, 0.0, 0.0125 + 0.0011), False)],
)
def test_motion_boundary_in_height_alone(
    position: tuple[float, float, float], settled: bool
) -> None:
    samples = _with(_samples(), -1, object_position_m=position)
    assert (assess(samples, RUBRIC).success is True) is settled


def test_too_few_samples_do_not_decide() -> None:
    samples = [StateSample(0, TARGET, TARGET, False)]
    outcome = assess(samples, RUBRIC)
    assert (outcome.success, outcome.label) == (None, "insufficient_evidence")


def test_ten_samples_do_not_decide_and_eleven_do() -> None:
    assert assess(_samples(dwell=DWELL - 3), RUBRIC).success is None
    assert len(_samples(dwell=DWELL - 3)) == DWELL
    assert assess(_samples(dwell=DWELL - 2), RUBRIC).success is False
    assert len(_samples(dwell=DWELL - 2)) == DWELL + 1


@pytest.mark.parametrize(
    "changes",
    [
        {"object_position_m": None},
        {"target_position_m": None},
        {"grasped": None},
        {"object_position_m": (math.nan, 0.0, 0.0125)},
        {"object_position_m": (0.1, math.nan, 0.0125)},
        {"object_position_m": (0.1, 0.0, math.nan)},
        {"object_position_m": (math.inf, 0.0, 0.0125)},
        {"target_position_m": (math.nan, 0.0, 0.0125)},
        {"target_position_m": (0.1, 0.0, -math.inf)},
    ],
)
@pytest.mark.parametrize("index", [0, 1, -1])
def test_an_invalid_sample_anywhere_does_not_decide(index: int, changes: dict[str, object]) -> None:
    outcome = assess(_with(_samples(), index, **changes), RUBRIC)
    assert (outcome.success, outcome.label) == (None, "insufficient_evidence")


def test_all_nan_is_never_a_success() -> None:
    nan = (math.nan, math.nan, math.nan)
    samples = [StateSample(i, nan, nan, False) for i in range(20)]
    assert assess(samples, RUBRIC).success is None


@pytest.mark.parametrize(
    ("changes", "label"),
    [
        ({"lifted": False, "grasped_at_end": True}, "never_lifted"),
        ({"final": (0.2, 0.0, 0.05), "grasped_at_end": True}, "still_grasped"),
        ({"final": (0.2, 0.0, 0.05)}, "not_on_table"),
    ],
)
def test_label_order_when_several_conditions_fail(changes: dict[str, object], label: str) -> None:
    assert assess(_samples(**changes), RUBRIC).label == label  # type: ignore[arg-type]


def test_outside_target_outranks_not_settled() -> None:
    samples = _with(_samples((0.2, 0.0, 0.0125)), -1, object_position_m=(0.21, 0.0, 0.0125))
    assert assess(samples, RUBRIC).label == "outside_target"


def _packets(position: list[float] | None, grasped: float | None) -> list[dict[str, object]]:
    return [
        {"stream": "object_position", "valid": position is not None, "value": position},
        {"stream": "target_position", "valid": True, "value": [0.1, 0.0, 0.0125]},
        {
            "stream": "object_grasped",
            "valid": grasped is not None,
            "value": None if grasped is None else [grasped],
        },
    ]


def test_samples_are_the_first_observation_then_each_next_observation() -> None:
    records = [
        {
            "observations": _packets([0.0, 0.0, 0.1], 0.0),
            "next_observations": _packets([0.0, 0.0, 0.2], 1.0),
        },
        {
            "observations": _packets([9.0, 9.0, 9.0], 0.0),
            "next_observations": _packets([0.0, 0.0, 0.3], 0.0),
        },
    ]
    samples = samples_from_records(records)
    assert [s.step for s in samples] == [0, 1, 2]
    assert [s.object_position_m for s in samples] == [
        (0.0, 0.0, 0.1),
        (0.0, 0.0, 0.2),
        (0.0, 0.0, 0.3),
    ]
    assert [s.grasped for s in samples] == [False, True, False]


def test_no_records_give_no_samples() -> None:
    assert samples_from_records([]) == []


@pytest.mark.parametrize(
    ("position", "grasped", "field"),
    [
        (None, 0.0, "object_position_m"),
        ([0.0, 0.0], 0.0, "object_position_m"),
        ([0.0, 0.0, 0.1], None, "grasped"),
        ([0.0, 0.0, 0.1], math.nan, "grasped"),
    ],
)
def test_bad_recorded_values_become_invalid_samples(
    position: list[float] | None, grasped: float | None, field: str
) -> None:
    good = _packets([0.0, 0.0, 0.1], 0.0)
    records = [{"observations": _packets(position, grasped), "next_observations": good}]
    assert getattr(samples_from_records(records)[0], field) is None


def test_a_value_marked_invalid_is_not_used() -> None:
    packets = _packets([0.0, 0.0, 0.1], 0.0)
    packets[0]["valid"] = False
    records = [{"observations": packets, "next_observations": packets}]
    assert samples_from_records(records)[0].object_position_m is None


def test_rubric_refuses_missing_or_extra_keys() -> None:
    raw = {
        "rubric_version": "x",
        "target_radius_m": 1.0,
        "rest_height_m": 1.0,
        "rest_height_tolerance_m": 1.0,
        "min_lift_above_rest_m": 1.0,
        "max_step_motion_m": 1.0,
        "dwell_steps": 1,
    }
    assert PlaceRubric.from_mapping(raw).dwell_steps == 1
    with pytest.raises(ValueError, match="rubric keys"):
        PlaceRubric.from_mapping({**raw, "extra": 1})
    del raw["dwell_steps"]
    with pytest.raises(ValueError, match="rubric keys"):
        PlaceRubric.from_mapping(raw)


def test_frozen_rubric_loads() -> None:
    root = Path(__file__).resolve().parents[1]
    frozen = json.loads((root / "evals" / "M0-exit-tests.json").read_text(encoding="utf-8"))
    assert PlaceRubric.from_mapping(frozen["place_rubric"]).rubric_version == "m0-place-1"


def test_judge_implements_the_interface() -> None:
    assert isinstance(PickPlaceJudge(RUBRIC), SuccessJudge)


def _episode_on_disk(tmp_path: Path, path: str = "transitions.jsonl") -> tuple[Path, bytes]:
    data = b'{"observations": [], "next_observations": []}\n'
    target = tmp_path / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    manifest = {
        "data": {"transitions_artifact": {"path": path, "sha256": hashlib.sha256(data).hexdigest()}}
    }
    (tmp_path / "episode.json").write_text(json.dumps(manifest), encoding="utf-8")
    return target, data


def test_judge_reads_the_file_the_manifest_names(tmp_path: Path) -> None:
    _episode_on_disk(tmp_path, "sub/transitions.jsonl")
    (tmp_path / "transitions.jsonl").write_text("planted", encoding="utf-8")
    verdict, note = PickPlaceJudge(RUBRIC).judge(str(tmp_path))
    assert verdict is None
    assert note.startswith("insufficient_evidence")
    assert "hash" not in note


def test_judge_does_not_decide_on_a_changed_file(tmp_path: Path) -> None:
    target, data = _episode_on_disk(tmp_path)
    target.write_bytes(data + b"\n")
    verdict, note = PickPlaceJudge(RUBRIC).judge(str(tmp_path))
    assert verdict is None
    assert "hash" in note


def test_judge_refuses_a_path_outside_the_episode(tmp_path: Path) -> None:
    episode = tmp_path / "episode"
    episode.mkdir()
    (tmp_path / "x.jsonl").write_text("", encoding="utf-8")
    manifest = {"data": {"transitions_artifact": {"path": "../x.jsonl", "sha256": ""}}}
    (episode / "episode.json").write_text(json.dumps(manifest), encoding="utf-8")
    verdict, note = PickPlaceJudge(RUBRIC).judge(str(episode))
    assert verdict is None
    assert "unsafe" in note


def test_judge_refuses_an_absolute_path(tmp_path: Path) -> None:
    target = tmp_path / "x.jsonl"
    target.write_text("", encoding="utf-8")
    manifest = {"data": {"transitions_artifact": {"path": str(target), "sha256": ""}}}
    episode = tmp_path / "episode"
    episode.mkdir()
    (episode / "episode.json").write_text(json.dumps(manifest), encoding="utf-8")
    verdict, note = PickPlaceJudge(RUBRIC).judge(str(episode))
    assert verdict is None
    assert "unsafe" in note


def test_outcome_code_imports_only_the_standard_library_and_itself() -> None:
    """ET-M0-4: the outcome shares nothing with a policy, a reward or a learned model."""
    outcome_dir = Path(__file__).resolve().parents[1] / "src" / "vishwaroop" / "outcome"
    assert list(outcome_dir.glob("*.py"))
    for path in outcome_dir.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    assert node.level == 1, f"{path.name} reaches outside the outcome package"
                    continue
                names = [node.module or ""]
            else:
                continue
            for name in names:
                assert name.split(".")[0] in sys.stdlib_module_names, f"{path.name}: {name}"
