"""The frozen verdict rules and the dev evaluator's refusals. All data here is FABRICATED."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from vishwaroop.models.m1_scoring import (
    HORIZONS,
    MIN_DEV_EPISODES,
    bootstrap_interval,
    conformal_scale,
    et_m1_1_passes,
    et_m1_3_passes,
    lowest_baseline,
    reductions_at_each_horizon,
)

GOOD = [0.5] * HORIZONS
STREAMS = {"joint_position": GOOD, "object_position": GOOD}
CALIBRATED = {"spearman": [0.6] * HORIZONS, "calibrated_coverage": [0.9] * HORIZONS}
UNCERTAIN = {"joint_position": CALIBRATED, "object_position": CALIBRATED}


def test_the_lowest_baseline_is_taken_at_each_horizon() -> None:
    a, b = [1.0] * HORIZONS, [2.0] * HORIZONS
    b[3] = 0.5
    lowest = lowest_baseline({"a": a, "b": b})
    assert lowest[0] == 1.0
    assert lowest[3] == 0.5


def test_a_baseline_with_missing_horizons_is_refused() -> None:
    with pytest.raises(ValueError, match="horizons"):
        lowest_baseline({"a": [1.0]})
    with pytest.raises(ValueError, match="no baselines"):
        lowest_baseline({})


def test_a_reduction_is_against_the_lowest_baseline() -> None:
    values = reductions_at_each_horizon([0.8] * HORIZONS, {"a": [1.0] * HORIZONS})
    assert values == pytest.approx([0.2] * HORIZONS)


def test_et_m1_1_passes_only_when_everything_reaches_it() -> None:
    assert et_m1_1_passes({"0": STREAMS, "1": STREAMS}, MIN_DEV_EPISODES)
    one_horizon_short = [0.5] * (HORIZONS - 1) + [0.19]
    worse = {**STREAMS, "object_position": one_horizon_short}
    assert not et_m1_1_passes({"0": STREAMS, "1": worse}, MIN_DEV_EPISODES)


def test_et_m1_1_treats_exactly_twenty_percent_as_a_pass() -> None:
    exact = {"joint_position": [0.2] * HORIZONS, "object_position": [0.2] * HORIZONS}
    assert et_m1_1_passes({"0": exact}, MIN_DEV_EPISODES)


def test_et_m1_1_refuses_too_few_episodes_or_a_missing_stream() -> None:
    with pytest.raises(ValueError, match="dev episodes"):
        et_m1_1_passes({"0": STREAMS}, MIN_DEV_EPISODES - 1)
    with pytest.raises(ValueError, match="object_position"):
        et_m1_1_passes({"0": {"joint_position": GOOD}}, MIN_DEV_EPISODES)
    with pytest.raises(ValueError, match="no seeds"):
        et_m1_1_passes({}, MIN_DEV_EPISODES)


def test_et_m1_3_needs_rank_and_coverage_at_every_horizon() -> None:
    assert et_m1_3_passes({"0": UNCERTAIN}, MIN_DEV_EPISODES)
    low_rank = {**CALIBRATED, "spearman": [0.6] * (HORIZONS - 1) + [0.49]}
    assert not et_m1_3_passes({"0": {**UNCERTAIN, "joint_position": low_rank}}, MIN_DEV_EPISODES)
    under = {**CALIBRATED, "calibrated_coverage": [0.9] * (HORIZONS - 1) + [0.79]}
    assert not et_m1_3_passes({"0": {**UNCERTAIN, "object_position": under}}, MIN_DEV_EPISODES)
    over = {**CALIBRATED, "calibrated_coverage": [1.0] * HORIZONS}
    assert et_m1_3_passes({"0": {**UNCERTAIN, "object_position": over}}, MIN_DEV_EPISODES)


def test_conformal_scale_rounds_its_rank_up() -> None:
    assert conformal_scale([float(item) for item in range(1, 11)]) == 10.0
    assert conformal_scale([float(item) for item in range(1, 101)]) == 91.0


def test_conformal_scale_refuses_nothing_and_non_finite_values() -> None:
    with pytest.raises(ValueError, match="no calibration"):
        conformal_scale([])
    with pytest.raises(ValueError, match="finite"):
        conformal_scale([1.0, float("nan")])


def test_bootstrap_interval_brackets_a_known_reduction() -> None:
    counts = [10] * 50
    learned = [10 * (0.5 + 0.1 * (item % 3)) ** 2 for item in range(50)]
    baseline = {"a": [10.0 * 1.0] * 50}
    low, high = bootstrap_interval(learned, counts, baseline, seed=1, resamples=500)
    point = 1.0 - (sum(learned) / sum(counts)) ** 0.5
    assert low <= point <= high
    assert high - low < 0.2


def test_bootstrap_interval_refuses_mismatched_episodes() -> None:
    with pytest.raises(ValueError, match="differ"):
        bootstrap_interval([1.0], [1, 2], {"a": [1.0]})
    with pytest.raises(ValueError, match="different episodes"):
        bootstrap_interval([1.0], [1], {"a": [1.0, 2.0]})


def _ledger(path: Path, records: list[dict[str, str]]) -> Path:
    path.write_text("".join(json.dumps(item) + "\n" for item in records), encoding="utf-8")
    return path


def _plan(tmp_path: Path) -> tuple[Path, str]:
    path = tmp_path / "plan.json"
    path.write_text('{"seeds": [0]}', encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest(tmp_path: Path, name: str, entries: list[dict[str, object]]) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps({"episodes": entries}), encoding="utf-8")
    return path


def test_a_changed_plan_is_refused(tmp_path: Path) -> None:
    from vishwaroop.models.m1_evaluate import check_plan

    path, digest = _plan(tmp_path)
    assert check_plan(path, digest) == {"seeds": [0]}
    path.write_text('{"seeds": [1]}', encoding="utf-8")
    with pytest.raises(ValueError, match="frozen plan"):
        check_plan(path, digest)


def test_dev_is_scored_once(tmp_path: Path) -> None:
    from vishwaroop.models.m1_evaluate import PURPOSE, check_not_scored

    crashed = {"status": "started", "purpose": PURPOSE, "run_id": "a"}
    check_not_scored(_ledger(tmp_path / "one.jsonl", [crashed]))
    other = {"status": "completed", "run_id": "b"}
    check_not_scored(_ledger(tmp_path / "two.jsonl", [crashed, other]))
    finished = {"status": "completed", "run_id": "a"}
    with pytest.raises(ValueError, match="already scored"):
        check_not_scored(_ledger(tmp_path / "three.jsonl", [crashed, finished]))


def _episode(root: Path, name: str, seed: int) -> dict[str, object]:
    packets = [
        {"stream": "joint_position", "value": [0.0] * 6},
        {"stream": "object_position", "value": [0.0] * 3},
        {"stream": "target_position", "value": [0.0] * 3},
        {"stream": "object_grasped", "value": [0.0]},
    ]
    record = {
        "observations": packets,
        "next_observations": packets,
        "action": {"requested": [0.0] * 6},
    }
    directory = root / name
    directory.mkdir()
    raw = (json.dumps(record) + "\n").encode("utf-8")
    (directory / "transitions.jsonl").write_bytes(raw)
    return {
        "episode_id": name,
        "partition": "dev",
        "family": "m0-scripted-dev-x",
        "seed": seed,
        "path": name,
        "transitions_sha256": hashlib.sha256(raw).hexdigest(),
    }


def test_load_dev_refuses_a_train_seed_and_a_repeat_and_too_few(tmp_path: Path) -> None:
    from vishwaroop.models.m1_evaluate import load_dev

    good = _episode(tmp_path, "good", 8000)
    train_seed = _episode(tmp_path, "train-seed", 2000)
    with pytest.raises(ValueError, match="not a dev seed"):
        load_dev([_manifest(tmp_path, "a.json", [train_seed])], tmp_path)
    twice = _manifest(tmp_path, "b.json", [good])
    with pytest.raises(ValueError, match="two manifests"):
        load_dev([twice, twice], tmp_path)
    with pytest.raises(ValueError, match="dev episodes"):
        load_dev([twice], tmp_path)


def test_load_dev_ignores_train_entries(tmp_path: Path) -> None:
    from vishwaroop.models.m1_evaluate import load_dev

    entries = [_episode(tmp_path, f"dev-{seed}", seed) for seed in range(8000, 8200)]
    entries.append({"episode_id": "t", "partition": "train", "seed": 2000})
    loaded = load_dev([_manifest(tmp_path, "c.json", entries)], tmp_path)
    assert len(loaded) == 200
    assert {item.family for item in loaded} == {"m0-scripted-dev-x"}


def _fake_stats(torch: object) -> tuple[object, dict[str, object]]:
    from types import SimpleNamespace

    from vishwaroop.models.cube_study import _Kinematics

    torch.manual_seed(5)  # type: ignore[attr-defined]
    states = torch.randn(300, 14, 13) * 0.01  # type: ignore[attr-defined]
    actions = torch.randn(300, 13, 6) * 0.01  # type: ignore[attr-defined]
    data = SimpleNamespace(
        windows_s=states,
        windows_a=actions,
        delta_std=torch.ones(13),  # type: ignore[attr-defined]
    )
    stats = {
        "state_mean": torch.zeros(13),  # type: ignore[attr-defined]
        "state_std": torch.ones(13),  # type: ignore[attr-defined]
        "delta_std": torch.ones(13),  # type: ignore[attr-defined]
        "lag": torch.ones(6),  # type: ignore[attr-defined]
        "action_mean": torch.zeros(6),  # type: ignore[attr-defined]
        "action_std": torch.ones(6),  # type: ignore[attr-defined]
        "kinematics": _Kinematics("cpu"),
    }
    return data, stats


def test_torch_a_resumed_latent_training_matches_an_unbroken_one(tmp_path: Path) -> None:
    torch = pytest.importorskip("torch")
    from vishwaroop.models.latent_predictor import train

    data, stats = _fake_stats(torch)
    unbroken, _ = train(data, stats, 3, 3, device="cpu")
    path = tmp_path / "checkpoint.pt"
    train(data, stats, 3, 2, path, device="cpu")
    resumed, training = train(data, stats, 3, 3, path, device="cpu")
    assert training["resumed_at_epoch"] == 2
    for name, value in unbroken.state_dict().items():
        assert torch.equal(value, resumed.state_dict()[name]), name


def test_torch_latent_load_refuses_an_unfinished_training(tmp_path: Path) -> None:
    torch = pytest.importorskip("torch")
    from vishwaroop.models.latent_predictor import load, train

    data, stats = _fake_stats(torch)
    path = tmp_path / "checkpoint.pt"
    train(data, stats, 3, 1, path, device="cpu")
    with pytest.raises(ValueError, match="stopped at epoch 1"):
        load(path, "cpu", 2)
    assert load(path, "cpu", 1) is not None


def test_torch_imagination_does_not_see_future_states() -> None:
    torch = pytest.importorskip("torch")
    from vishwaroop.models.latent_predictor import new_modules, predict

    data, stats = _fake_stats(torch)
    modules = new_modules("cpu")
    modules.eval()
    states = data.windows_s[:4].clone()
    actions = data.windows_a[:4]
    first, _ = predict(modules, stats, states, actions)
    states[:, 4:] += 1.0  # everything after the observation-update steps
    second, _ = predict(modules, stats, states, actions)
    assert torch.equal(first, second)


def test_torch_observation_update_does_use_the_observed_states() -> None:
    torch = pytest.importorskip("torch")
    from vishwaroop.models.latent_predictor import new_modules, predict

    data, stats = _fake_stats(torch)
    modules = new_modules("cpu")
    modules.eval()
    states = data.windows_s[:4].clone()
    actions = data.windows_a[:4]
    first, _ = predict(modules, stats, states, actions)
    states[:, 1] += 0.5  # an observed step, inside the history
    second, _ = predict(modules, stats, states, actions)
    assert not torch.equal(first, second)


def test_torch_tied_values_share_their_rank() -> None:
    torch = pytest.importorskip("torch")
    from vishwaroop.models.m1_evaluate import tied_spearman

    a = torch.tensor([1.0, 2.0, 3.0, 4.0], dtype=torch.float64)
    assert tied_spearman(a, a * 10) == pytest.approx(1.0)
    assert tied_spearman(a, -a) == pytest.approx(-1.0)
    tied = torch.tensor([1.0, 1.0, 2.0, 2.0], dtype=torch.float64)
    assert tied_spearman(tied, a) == pytest.approx(2.0 / 5.0**0.5, rel=1e-9)
    with pytest.raises(ValueError, match="differ"):
        tied_spearman(torch.ones(4, dtype=torch.float64), a)


def test_the_frozen_plan_is_what_the_evaluator_requires(root: Path) -> None:
    from vishwaroop.models.cube_study import VARIANTS
    from vishwaroop.models.m1_evaluate import PLAN_PATH, PLAN_SHA256, check_plan

    plan = check_plan(root / PLAN_PATH)
    assert plan["changes_a_threshold"] is False
    assert plan["final_variant"] in VARIANTS
    assert plan["ET-M1-3"]["streams_each_required_to_pass"] == [
        "joint_position",
        "object_position",
    ]
    assert hashlib.sha256((root / PLAN_PATH).read_bytes()).hexdigest() == PLAN_SHA256


def test_the_top_up_reaches_the_exit_tests_minimum_on_new_dev_seeds(root: Path) -> None:
    from vishwaroop.sim.collect import load_plan

    plan = load_plan(root / "evals" / "M1-dev-topup-plan.json")
    first = json.loads((root / "evals" / "M0-dataset-plan.json").read_text(encoding="utf-8"))
    earlier = {
        (family["variant"], seed)
        for family in first["families"]
        if family["partition"] == "dev"
        for seed in range(family["first_seed"], family["first_seed"] + family["count"])
    }
    added = {
        (family["variant"], seed)
        for family in plan["families"]
        for seed in range(family["first_seed"], family["first_seed"] + family["count"])
    }
    assert not earlier & added
    assert {variant for variant, _ in added} == {variant for variant, _ in earlier}
    assert len(earlier) + len(added) >= MIN_DEV_EPISODES
