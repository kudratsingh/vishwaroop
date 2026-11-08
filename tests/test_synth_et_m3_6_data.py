"""ET-M3-6's training sets: counts, order, refusals and F1's draw order. Episodes, manifests and
arrays here are FABRICATED; no simulator ran and nothing here is evidence about the M0 data."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from vishwaroop.models import et_m3_6_data as data
from vishwaroop.models.et_m3_6_data import (
    BASE_WINDOWS,
    W_STAR,
    DataRefusalError,
    base_split,
    check_arm,
    check_base,
    check_record,
    f_star_episodes,
    load_m3_eval,
    load_m3_train,
    m0_train_entries,
    read_manifest,
    split_m0,
    truncate_counts,
    windows_in,
)
from vishwaroop.models.pilot_data import EpisodeArrays
from vishwaroop.synth.m3_record import EVAL_FAMILY, LATERAL_FAMILY, NOMINAL_FAMILY
from vishwaroop.synth.protocol import ProtocolRefusalError

TARGET = "m0-scripted-missed-grasp"
OTHERS = (
    "m0-scripted-early-release",
    "m0-scripted-no-release",
    "m0-scripted-noisy-actions",
    "m0-scripted-nominal",
    "m0-scripted-timeout",
    "m0-scripted-wrong-place",
)


def _episode(seed: int, family: str, windows: int) -> EpisodeArrays:
    steps = windows + 12
    states = [[float(seed)] * 13 for _ in range(steps + 1)]
    actions = [[0.0] * 6 for _ in range(steps)]
    return EpisodeArrays(seed, states, actions, family)


def _m0_like(base_windows: int = BASE_WINDOWS) -> list[EpisodeArrays]:
    """260 train episodes laid out like M0's: 27 F_star (4,161 windows), 3 excluded target
    episodes, 23 no-harm and 207 base episodes (``base_windows`` windows), interleaved."""
    target = []
    for seed in range(2000, 2030):
        windows = 100 if seed % 10 == 0 else (157 if seed == 2029 else 154)
        target.append(_episode(seed, TARGET, windows))
    no_harm = [_episode(3000 + 10 * i, OTHERS[i % 6], 120) for i in range(23)]
    base_seeds = [seed for seed in range(4001, 5000) if seed % 10][:207]
    per, extra = divmod(base_windows, 207)
    base = [
        _episode(seed, OTHERS[i % 6], per + (extra if i == 0 else 0))
        for i, seed in enumerate(base_seeds)
    ]
    others = [*base[:100], *no_harm, *base[100:]]
    return [*others[:50], *target, *others[50:]]


def test_the_fabricated_layout_is_m0s_shape() -> None:
    episodes = _m0_like()
    assert len(episodes) == 260
    assert sum(1 for item in episodes if item.family == TARGET) == 30


def test_the_base_is_207_episodes_and_31031_windows_in_order() -> None:
    episodes = _m0_like()
    base, no_harm = base_split(episodes)
    assert len(base) == 207 and sum(windows_in(item) for item in base) == 31031
    assert len(no_harm) == 23 and all(item.seed % 10 == 0 for item in no_harm)
    assert all(item.family != TARGET for item in base + no_harm)
    order = [item.seed for item in episodes if item in base]
    assert [item.seed for item in base] == order


def test_a_base_count_other_than_31031_stops_before_training() -> None:
    with pytest.raises(DataRefusalError, match="stopped before training"):
        base_split(_m0_like(BASE_WINDOWS - 1))
    episodes = _m0_like()
    base = [item for item in episodes if item.family != TARGET and item.seed % 10]
    with pytest.raises(DataRefusalError, match="206 episodes"):
        check_base(base[1:])


def test_f_star_is_27_episodes_and_4161_windows() -> None:
    chosen = f_star_episodes(_m0_like())
    assert len(chosen) == 27 and sum(windows_in(item) for item in chosen) == W_STAR
    assert all(item.family == TARGET and item.seed % 10 for item in chosen)
    without_one = [item for item in _m0_like() if item.seed != 2001]
    with pytest.raises(DataRefusalError, match="F_star has 26 episodes"):
        f_star_episodes(without_one)


def test_split_m0_entries_follows_the_frozen_rule() -> None:
    entries = [
        {"episode_id": f"e{i}", "partition": "train", "family": family, "seed": seed}
        for i, (family, seed) in enumerate(
            [(TARGET, 2001), (TARGET, 2010), (OTHERS[0], 3001), (OTHERS[0], 3010)]
        )
    ]
    split = split_m0(entries)
    assert [e["seed"] for e in split.f_star] == [2001]
    assert [e["seed"] for e in split.excluded_target] == [2010]
    assert [e["seed"] for e in split.base] == [3001]
    assert [e["seed"] for e in split.no_harm] == [3010]
    with pytest.raises(DataRefusalError):
        split_m0([{**entries[0], "partition": "dev"}])


# --- records ---------------------------------------------------------------------------------


def _manifest(**changes: Any) -> dict[str, Any]:
    manifest = {
        "environment_kind": "physics_sim",
        "provenance": {"generator_model_artifact": None, "parent_episode_ids": []},
        "validation": {"statuses": []},
    }
    manifest.update(changes)
    return manifest


def test_an_imagined_record_is_refused() -> None:
    check_record(_manifest(), "x")
    with pytest.raises(DataRefusalError, match="imagined"):
        check_record(_manifest(environment_kind="imagined"), "x")
    with pytest.raises(DataRefusalError, match="generator_model_artifact"):
        check_record(
            _manifest(provenance={"generator_model_artifact": {"path": "g", "sha256": "0"}}), "x"
        )
    with pytest.raises(DataRefusalError, match="generated"):
        check_record(_manifest(validation={"statuses": ["generated"]}), "x")


def _packets(value: float) -> list[dict[str, Any]]:
    return [
        {"stream": "joint_position", "value": [value] * 6},
        {"stream": "object_position", "value": [value] * 3},
        {"stream": "target_position", "value": [value] * 3},
        {"stream": "object_grasped", "value": [0.0]},
    ]


def _write_episode(
    root: Path,
    family: str,
    seed: int,
    steps: int,
    partition: str = "train",
    **manifest_changes: Any,
) -> dict[str, Any]:
    episode_id = f"{family}-seed-{seed:06d}"
    path = root / episode_id
    path.mkdir(parents=True)
    records = [
        {
            "observations": _packets(float(step)),
            "next_observations": _packets(float(step + 1)),
            "action": {"requested": [float(step)] * 6},
        }
        for step in range(steps)
    ]
    raw = "".join(json.dumps(record) + "\n" for record in records).encode()
    (path / "transitions.jsonl").write_bytes(raw)
    manifest = _manifest(
        episode_id=episode_id,
        policy={"family_id": family},
        split={"partition": partition},
        data={"transitions_artifact": {"path": "transitions.jsonl", "sha256": _sha(raw)}},
    )
    manifest.update(manifest_changes)
    (path / "episode.json").write_text(json.dumps(manifest))
    return {"seed": seed, "family": family, "path": episode_id, "episode_id": episode_id}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def test_an_episode_whose_manifest_hash_differs_is_refused(tmp_path: Path) -> None:
    item = _write_episode(tmp_path, LATERAL_FAMILY, 11000, 20)
    with pytest.raises(DataRefusalError, match="sha256"):
        read_manifest(tmp_path / item["path"], "0" * 64)


def test_the_m3_loader_reads_train_blocks_past_8000(tmp_path: Path) -> None:
    kept = [_write_episode(tmp_path, LATERAL_FAMILY, 11000 + i, 20 + i) for i in range(3)]
    episodes = load_m3_train(kept, (LATERAL_FAMILY,), tmp_path)
    assert [item.seed for item in episodes] == [11000, 11001, 11002]
    assert [windows_in(item) for item in episodes] == [8, 9, 10]
    assert episodes[0].family == LATERAL_FAMILY


def test_a_dev_seed_in_a_training_set_is_refused(tmp_path: Path) -> None:
    kept = [
        _write_episode(tmp_path, LATERAL_FAMILY, 11000, 20),
        _write_episode(tmp_path, EVAL_FAMILY, 16000, 20, partition="dev"),
    ]
    with pytest.raises(ProtocolRefusalError, match="dev block 16"):
        load_m3_train(kept, (LATERAL_FAMILY, EVAL_FAMILY), tmp_path)
    for seed in (8000, 9999, 17000):
        with pytest.raises(ProtocolRefusalError, match="dev block"):
            load_m3_train([{"seed": seed}], (LATERAL_FAMILY,), tmp_path)
    with pytest.raises(ProtocolRefusalError, match="reserved"):
        load_m3_train([{"seed": 18000}], (LATERAL_FAMILY,), tmp_path)


@pytest.mark.parametrize(
    ("seed", "match"),
    [
        (10265, "held for ET-M3-1"),  # a held seed, whoever recorded it
        (10789, "held for ET-M3-1"),
        (10000, "block 10"),  # block 10, unheld
        (10999, "block 10"),
        (12000, "recorded on block 11"),  # a train block, but not WO-022's
    ],
)
def test_the_m3_loader_refuses_held_block_10_and_off_block_seeds(
    tmp_path: Path, seed: int, match: str
) -> None:
    kept = [
        _write_episode(tmp_path, LATERAL_FAMILY, 11000, 20),
        _write_episode(tmp_path, LATERAL_FAMILY, seed, 20),
    ]
    with pytest.raises(ProtocolRefusalError, match=match):
        load_m3_train(kept, (LATERAL_FAMILY,), tmp_path)


def test_the_m3_loader_refuses_an_imagined_record(tmp_path: Path) -> None:
    kept = [_write_episode(tmp_path, LATERAL_FAMILY, 11000, 20, environment_kind="imagined")]
    with pytest.raises(DataRefusalError, match="imagined"):
        load_m3_train(kept, (LATERAL_FAMILY,), tmp_path)
    generated = [
        _write_episode(
            tmp_path,
            NOMINAL_FAMILY,
            11001,
            20,
            provenance={"generator_model_artifact": {"path": "m", "sha256": "1" * 64}},
        )
    ]
    with pytest.raises(DataRefusalError, match="generator_model_artifact"):
        load_m3_train(generated, (NOMINAL_FAMILY,), tmp_path)


def test_the_m3_loader_refuses_another_family_or_partition(tmp_path: Path) -> None:
    kept = [_write_episode(tmp_path, NOMINAL_FAMILY, 11000, 20)]
    with pytest.raises(DataRefusalError, match="family"):
        load_m3_train(kept, (LATERAL_FAMILY,), tmp_path)
    wrong = [_write_episode(tmp_path, LATERAL_FAMILY, 11001, 20, split={"partition": "dev"})]
    with pytest.raises(DataRefusalError, match="partition"):
        load_m3_train(wrong, (LATERAL_FAMILY,), tmp_path)


def test_the_evaluation_loader_reads_60_block_16_episodes(tmp_path: Path) -> None:
    kept = [_write_episode(tmp_path, EVAL_FAMILY, 16000 + i, 15, "dev") for i in range(60)]
    assert len(load_m3_eval(kept, tmp_path)) == 60
    with pytest.raises(DataRefusalError, match="59"):
        load_m3_eval(kept[:59], tmp_path)
    moved = [*kept[:59], {**kept[59], "seed": 17000}]
    with pytest.raises(ProtocolRefusalError, match="block 16"):
        load_m3_eval(moved, tmp_path)


def test_m0s_manifest_must_be_the_frozen_one(tmp_path: Path) -> None:
    path = tmp_path / "m.json"
    path.write_text(json.dumps({"episodes": []}))
    with pytest.raises(DataRefusalError, match="not 267d77"):
        m0_train_entries(path)


# --- truncation and windows ------------------------------------------------------------------


def test_the_last_episode_is_cut_from_its_end_to_exactly_w_star() -> None:
    episodes = [_episode(11000 + i, LATERAL_FAMILY, 1000) for i in range(5)]
    counts, matched = truncate_counts(episodes)
    assert counts == [1000, 1000, 1000, 1000, 161] and matched
    with pytest.raises(DataRefusalError, match="after the windows reached"):
        truncate_counts([*episodes, _episode(11005, LATERAL_FAMILY, 10)])
    short, matched = truncate_counts(episodes[:2])
    assert short == [1000, 1000] and not matched


def test_f3_and_unknown_arms_are_refused() -> None:
    for arm in data.ARMS:
        assert check_arm(arm) == arm
    with pytest.raises(DataRefusalError, match="out of WO-022's scope"):
        check_arm("F3")
    with pytest.raises(DataRefusalError, match="unknown"):
        check_arm("F4")


# --- numpy: windows and F1 -------------------------------------------------------------------


def test_windows_keep_episode_order_and_cut_counts() -> None:
    np = pytest.importorskip("numpy")
    episodes = [_episode(11000, LATERAL_FAMILY, 3), _episode(11001, LATERAL_FAMILY, 2)]
    states, actions = data.windows_array(episodes, [3, 1])
    assert states.shape == (4, 14, 13) and actions.shape == (4, 13, 6)
    np.testing.assert_array_equal(states[:, 0, 0], [11000, 11000, 11000, 11001])


def test_f1_is_the_frozen_draw_in_the_frozen_order() -> None:
    np = pytest.importorskip("numpy")
    base_states = np.arange(BASE_WINDOWS * 14 * 13, dtype=np.float64).reshape(BASE_WINDOWS, 14, 13)
    base_actions = -np.arange(BASE_WINDOWS * 13 * 6, dtype=np.float64).reshape(BASE_WINDOWS, 13, 6)
    state_std = np.linspace(0.1, 1.3, 13)
    action_std = np.linspace(0.2, 0.7, 6)
    states, actions, idx = data.f1_augment(base_states, base_actions, state_std, action_std)

    rng = np.random.default_rng(1)
    expected_idx = rng.integers(0, 31031, 4161)
    state_noise = rng.standard_normal((4161, 4, 9)) * (0.05 * state_std[:9])
    action_noise = rng.standard_normal((4161, 13, 6)) * (0.05 * action_std)
    np.testing.assert_array_equal(idx, expected_idx)
    expected_states = base_states[expected_idx].copy()
    expected_states[:, :4, :9] += state_noise
    np.testing.assert_allclose(states, expected_states, rtol=0, atol=1e-9)
    np.testing.assert_allclose(
        actions, base_actions[expected_idx] + action_noise, rtol=0, atol=1e-9
    )
    # targets, target_position and object_grasped untouched
    np.testing.assert_array_equal(states[:, 4:], base_states[idx][:, 4:])
    np.testing.assert_array_equal(states[:, :4, 9:], base_states[idx][:, :4, 9:])
    assert states.shape == (W_STAR, 14, 13) and actions.shape == (W_STAR, 13, 6)
    again = data.f1_augment(base_states, base_actions, state_std, action_std)
    assert data.array_digest(*again) == data.array_digest(states, actions, idx)


def test_f1_refuses_a_base_of_another_size() -> None:
    np = pytest.importorskip("numpy")
    with pytest.raises(DataRefusalError, match="31031"):
        data.f1_augment(np.zeros((10, 14, 13)), np.zeros((10, 13, 6)), np.ones(13), np.ones(6))
