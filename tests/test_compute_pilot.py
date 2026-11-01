"""The pilot's data loading and memory parsing, with no torch. Fixtures are FABRICATED."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from vishwaroop.models.compute_pilot import _parse_time_output
from vishwaroop.models.pilot_data import load_train, split_holdout, state_vector


def _packets(base: float) -> list[dict[str, Any]]:
    return [
        {"stream": "joint_position", "value": [base] * 6},
        {"stream": "object_position", "value": [base] * 3},
        {"stream": "target_position", "value": [base] * 3},
        {"stream": "object_grasped", "value": [0.0]},
    ]


def _episode(root: Path, name: str, seed: int, partition: str) -> dict[str, Any]:
    directory = root / name
    directory.mkdir()
    record = {
        "action": {"requested": [0.1] * 6},
        "observations": _packets(0.0),
        "next_observations": _packets(1.0),
    }
    raw = (json.dumps(record) + "\n").encode()
    (directory / "transitions.jsonl").write_bytes(raw)
    return {
        "episode_id": name,
        "path": name,
        "seed": seed,
        "partition": partition,
        "transitions_sha256": hashlib.sha256(raw).hexdigest(),
    }


def _manifest(root: Path, entries: list[dict[str, Any]]) -> Path:
    path = root / "manifest.json"
    path.write_text(json.dumps({"episodes": entries}), encoding="utf-8")
    return path


def test_loads_train_and_never_dev(tmp_path: Path) -> None:
    train = _episode(tmp_path, "a", 2000, "train")
    dev = _episode(tmp_path, "b", 8000, "dev")
    loaded = load_train(_manifest(tmp_path, [train, dev]), tmp_path)
    assert [item.seed for item in loaded] == [2000]
    assert len(loaded[0].states) == len(loaded[0].actions) + 1


def test_refuses_a_dev_seed_labelled_train(tmp_path: Path) -> None:
    forged = _episode(tmp_path, "a", 8000, "train")
    with pytest.raises(ValueError, match="dev seed"):
        load_train(_manifest(tmp_path, [forged]), tmp_path)


def test_refuses_changed_transitions(tmp_path: Path) -> None:
    entry = _episode(tmp_path, "a", 2000, "train")
    (tmp_path / "a" / "transitions.jsonl").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="hash"):
        load_train(_manifest(tmp_path, [entry]), tmp_path)


def test_refuses_a_manifest_with_no_train(tmp_path: Path) -> None:
    dev = _episode(tmp_path, "a", 8000, "dev")
    with pytest.raises(ValueError, match="no train"):
        load_train(_manifest(tmp_path, [dev]), tmp_path)


def test_holdout_is_by_seed(tmp_path: Path) -> None:
    entries = [_episode(tmp_path, f"e{seed}", seed, "train") for seed in (2000, 2001, 2010)]
    fit, holdout = split_holdout(load_train(_manifest(tmp_path, entries), tmp_path))
    assert [item.seed for item in fit] == [2001]
    assert [item.seed for item in holdout] == [2000, 2010]


def test_state_vector_refuses_an_invalid_stream() -> None:
    packets = _packets(0.0)
    packets[1]["value"] = None
    with pytest.raises(ValueError, match="object_position"):
        state_vector(packets)


def test_parses_macos_time_output() -> None:
    text = "  531054592  maximum resident set size\n  379995600  peak memory footprint\n"
    assert _parse_time_output(text) == {
        "peak_footprint_bytes": 379995600,
        "max_rss_bytes": 531054592,
    }


def test_time_output_without_a_figure_is_refused() -> None:
    with pytest.raises(ValueError, match="peak memory footprint"):
        _parse_time_output("  531054592  maximum resident set size\n")
