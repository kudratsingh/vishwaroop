"""The frozen verdict rules and the dev evaluator's refusals. All data here is FABRICATED."""

from __future__ import annotations

import hashlib
import json
import random
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

    runs = tmp_path / "runs"
    crashed = {"status": "started", "purpose": PURPOSE, "run_id": "a"}
    check_not_scored(_ledger(tmp_path / "one.jsonl", [crashed]), runs)
    other = {"status": "completed", "run_id": "b"}
    check_not_scored(_ledger(tmp_path / "two.jsonl", [crashed, other]), runs)
    finished = {"status": "completed", "run_id": "a"}
    with pytest.raises(ValueError, match="already scored"):
        check_not_scored(_ledger(tmp_path / "three.jsonl", [crashed, finished]), runs)


@pytest.mark.parametrize("name", ["m1_dev_evaluation.json", "m1_dev_evaluation.json.partial"])
def test_a_result_on_disk_stops_a_second_scoring_whatever_the_ledger_says(
    tmp_path: Path, name: str
) -> None:
    from vishwaroop.models.m1_evaluate import PURPOSE, check_not_scored

    run = tmp_path / "runs" / "killed"
    run.mkdir(parents=True)
    (run / name).write_text("{}", encoding="utf-8")
    ledger = _ledger(
        tmp_path / "l.jsonl", [{"status": "started", "purpose": PURPOSE, "run_id": "killed"}]
    )
    with pytest.raises(ValueError, match="already scored"):
        check_not_scored(ledger, tmp_path / "runs")


def test_a_non_finite_result_writes_nothing(tmp_path: Path) -> None:
    from vishwaroop.models.m1_evaluate import write_result

    with pytest.raises(ValueError, match="JSON"):
        write_result(tmp_path, {"a": 1.0, "z": float("nan")})
    assert list(tmp_path.iterdir()) == []
    write_result(tmp_path, {"a": 1.0})
    assert [item.name for item in tmp_path.iterdir()] == ["m1_dev_evaluation.json"]


def test_a_changed_dev_manifest_is_refused(tmp_path: Path) -> None:
    from vishwaroop.models.m1_evaluate import check_manifests

    path = tmp_path / "m.json"
    path.write_text("{}", encoding="utf-8")
    good = hashlib.sha256(path.read_bytes()).hexdigest()
    check_manifests({path: good})
    path.write_text('{"episodes": []}', encoding="utf-8")
    with pytest.raises(ValueError, match="frozen manifest"):
        check_manifests({path: good})


def test_the_scorer_has_no_way_to_choose_what_it_scores(root: Path) -> None:
    from vishwaroop.models.m1_evaluate import (
        ENSEMBLE_RUN,
        FROZEN_DEV_MANIFESTS,
        FROZEN_EPOCHS,
        PLAN_PATH,
        check_manifests,
        check_plan,
        main,
    )

    assert FROZEN_EPOCHS in check_plan(root / PLAN_PATH)["allowed_epochs"]
    assert ENSEMBLE_RUN.name == "20261102T035805Z_ddb5d0d0"
    check_manifests({root / path: sha for path, sha in FROZEN_DEV_MANIFESTS.items()})
    with pytest.raises(SystemExit):
        main(["--epochs", "100"])
    with pytest.raises(SystemExit):
        main(["--ensemble-run", "runs/other"])


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


def _moving_episode(
    root: Path, name: str, seed: int, partition: str, family: str
) -> dict[str, object]:
    chooser = random.Random(seed)
    joints = [chooser.uniform(-0.3, 0.3) for _ in range(6)]
    cube = [0.2, 0.05, 0.0125]
    flag = 0.0
    lines = []

    def packets() -> list[dict[str, object]]:
        return [
            {"stream": "joint_position", "value": list(joints)},
            {"stream": "object_position", "value": list(cube)},
            {"stream": "target_position", "value": [0.1, 0.1, 0.05]},
            {"stream": "object_grasped", "value": [flag]},
        ]

    for step in range(40):
        before = packets()
        action = [value + chooser.gauss(0.0, 0.02) for value in joints]
        joints = [a + 0.5 * (b - a) for a, b in zip(joints, action, strict=True)]
        flag = 1.0 if 10 <= step < 20 else 0.0
        if flag:
            cube = [value + chooser.gauss(0.0, 0.002) for value in cube]
        lines.append(
            json.dumps(
                {
                    "observations": before,
                    "next_observations": packets(),
                    "action": {"requested": action},
                }
            )
        )
    directory = root / name
    directory.mkdir()
    raw = ("\n".join(lines) + "\n").encode("utf-8")
    (directory / "transitions.jsonl").write_bytes(raw)
    return {
        "episode_id": name,
        "partition": partition,
        "family": family,
        "seed": seed,
        "path": name,
        "transitions_sha256": hashlib.sha256(raw).hexdigest(),
    }


def _fabricated_scoring(
    torch: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[object, dict[str, object], object]:
    """Fabricated episodes, and untrained models recorded as if trained, in a scratch directory."""
    from functools import partial

    from vishwaroop.models import latent_predictor, m1_evaluate
    from vishwaroop.models.compute_pilot import _Data, _new_ensemble, _stats_of
    from vishwaroop.models.cube_study import (
        VARIANTS,
        _evaluate,
        _Kinematics,
        _metrics,
        phase_masks,
    )
    from vishwaroop.models.pilot_data import load_train, split_holdout

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        m1_evaluate, "bootstrap_interval", partial(bootstrap_interval, resamples=20)
    )
    train = [
        _moving_episode(tmp_path, f"train-{seed}", seed, "train", f"m0-f{seed % 2}")
        for seed in range(1000, 1020)
    ]
    dev = [
        _moving_episode(tmp_path, f"dev-{seed}", seed, "dev", f"m0-d{seed % 3}")
        for seed in range(8000 + MIN_DEV_EPISODES - 1, 7999, -1)
    ]
    train_path = _manifest(tmp_path, "train.json", train)
    dev_path = _manifest(tmp_path, "dev.json", [*dev, train[0]])
    name = "carry-contact-beta-fall"
    data = _Data(train_path, "cpu", split_holdout)
    stats = {**_stats_of(data), "kinematics": _Kinematics("cpu")}
    _, held = split_holdout(load_train(train_path, Path()))
    masks = phase_masks(held, len(data.holdout_s), "cpu")
    torch.manual_seed(0)  # type: ignore[attr-defined]
    layers = [(w.detach(), b.detach()) for w, b in _new_ensemble([19 + 3 * 19 + 3, 16, 16, 16, 26])]
    directory = tmp_path / "ens" / "work" / "seed" / name / "seed-0"
    directory.mkdir(parents=True)
    torch.save(  # type: ignore[attr-defined]
        {"epoch": 30, "layers": [list(layer) for layer in layers]}, directory / "checkpoint.pt"
    )
    recorded = {"predicted_flag": _evaluate(data, stats, VARIANTS[name], layers, masks, False)}
    (tmp_path / "ens" / "family_sweep.json").write_text(
        json.dumps({"epochs": 30, "holdouts": {"seed": {"variants": {name: {"0": recorded}}}}}),
        encoding="utf-8",
    )
    modules = latent_predictor.new_modules("cpu")
    modules.eval()
    directory = tmp_path / "lat" / "work" / "seed-0"
    directory.mkdir(parents=True)
    torch.save(  # type: ignore[attr-defined]
        {"epoch": 30, "modules": modules.state_dict()}, directory / latent_predictor.CHECKPOINT
    )
    with torch.no_grad():  # type: ignore[attr-defined]
        means, _ = latent_predictor.predict(modules, stats, data.holdout_s, data.holdout_a)
    metrics = _metrics(means, data.holdout_s[:, 4:], data.state_std, masks)
    (tmp_path / "lat" / "latent_predictor.json").write_text(
        json.dumps({"seeds_trained": {"0": {"predicted_flag": metrics}}}), encoding="utf-8"
    )
    plan = {"seeds": [0], "final_variant": name, "latent": {"epochs": 30}}
    inputs = m1_evaluate.Inputs(
        train_manifest=train_path,
        dev_manifests=(dev_path,),
        ensemble_run=tmp_path / "ens",
        latent_run=tmp_path / "lat",
        epochs=30,
        device="cpu",
    )
    return inputs, plan, m1_evaluate


def test_torch_the_scorer_runs_end_to_end_and_matches_a_separate_sum(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    torch = pytest.importorskip("torch")
    inputs, plan, m1_evaluate = _fabricated_scoring(torch, tmp_path, monkeypatch)
    report = m1_evaluate._evaluate(inputs, plan, {})  # type: ignore[attr-defined]
    assert report["dev_episodes"] == MIN_DEV_EPISODES
    assert sum(report["episodes_by_family"].values()) == MIN_DEV_EPISODES
    assert set(report["verdicts"]) == {"ET-M1-1", "ET-M1-3"}
    json.dumps(report, allow_nan=False)
    cell = report["ensemble"]["0"]
    assert set(cell["phases_own_units"]) <= set(report["baselines_phases_own_units"]["constant"])
    # the constant baseline, summed by hand from the fabricated files, in another order
    squares = [0.0] * HORIZONS
    count = 0
    for line_file in sorted(tmp_path.glob("dev-*/transitions.jsonl")):
        records = [json.loads(line) for line in line_file.read_text("utf-8").splitlines()]
        cubes = [records[0]["observations"][1]["value"]]
        cubes.extend(record["next_observations"][1]["value"] for record in records)
        for start in range(len(cubes) - 14 + 1):
            count += 1
            for h in range(HORIZONS):
                squares[h] += sum(
                    (a - b) ** 2
                    for a, b in zip(cubes[start + 4 + h], cubes[start + 3], strict=True)
                )
    expected = [(value / (3 * count)) ** 0.5 for value in squares]
    got = report["baselines_own_units"]["constant"]["object_position"]
    assert got == pytest.approx(expected, rel=1e-4)
    assert report["dev_windows"] == count


def test_torch_the_scorer_refuses_a_model_that_does_not_reproduce(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    torch = pytest.importorskip("torch")
    inputs, plan, m1_evaluate = _fabricated_scoring(torch, tmp_path, monkeypatch)
    path = inputs.ensemble_run / "family_sweep.json"  # type: ignore[attr-defined]
    sweep = json.loads(path.read_text(encoding="utf-8"))
    cell = sweep["holdouts"]["seed"]["variants"][plan["final_variant"]]["0"]  # type: ignore[index]
    cell["predicted_flag"]["streams_own_units"]["joint_position"][4] *= 1.01
    path.write_text(json.dumps(sweep), encoding="utf-8")
    with pytest.raises(ValueError, match="when trained"):
        m1_evaluate._evaluate(inputs, plan, {})  # type: ignore[attr-defined]


def test_torch_the_scorer_refuses_the_wrong_epochs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace

    torch = pytest.importorskip("torch")
    inputs, plan, m1_evaluate = _fabricated_scoring(torch, tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="epochs"):
        m1_evaluate._evaluate(replace(inputs, epochs=100), plan, {})  # type: ignore[attr-defined,type-var]
