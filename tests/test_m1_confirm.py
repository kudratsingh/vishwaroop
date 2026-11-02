"""The refinement's frozen accept rule and the confirmation set's refusals. Data is FABRICATED."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from vishwaroop.models.m1_confirm import (
    RULE_PATH,
    RULE_SHA256,
    accepts,
    check_hash,
    check_not_run,
    load_confirmation,
)

LOW = [1.0] * 10
HIGH = [2.0] * 10


def test_the_rule_is_the_frozen_one(root: Path) -> None:
    check_hash(root / RULE_PATH, RULE_SHA256)
    rule = json.loads((root / RULE_PATH).read_text(encoding="utf-8"))
    assert rule["changes_a_threshold"] is False


def test_accepted_when_held_is_lower_everywhere_and_free_never_higher() -> None:
    assert accepts(LOW, HIGH, LOW, LOW)
    assert accepts(LOW, HIGH, LOW, HIGH)


def test_a_tie_on_held_at_one_horizon_fails() -> None:
    tied = [1.0] + [0.5] * 9
    assert not accepts(tied, [1.0] * 10, LOW, LOW)


def test_free_higher_at_one_horizon_fails_beyond_rounding() -> None:
    assert not accepts(LOW, HIGH, [1.0] * 9 + [1.0 + 2e-9], LOW)
    assert accepts(LOW, HIGH, [1.0] * 9 + [1.0 + 5e-10], LOW)


def test_mismatched_horizons_are_refused() -> None:
    with pytest.raises(ValueError, match="horizons"):
        accepts(LOW, HIGH, [1.0], LOW)


def test_a_second_scoring_is_refused(tmp_path: Path) -> None:
    check_not_run(tmp_path)
    (tmp_path / "r").mkdir()
    (tmp_path / "r" / "m1_confirm.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="one scoring"):
        check_not_run(tmp_path)


def test_an_episode_outside_the_fresh_blocks_is_refused(tmp_path: Path) -> None:
    entry = {"episode_id": "x", "seed": 2000, "path": "x", "transitions_sha256": "0" * 64}
    with pytest.raises(ValueError, match="fresh block"):
        load_confirmation({"episodes": [entry]}, tmp_path)
    with pytest.raises(ValueError, match="empty"):
        load_confirmation({"episodes": []}, tmp_path)


def test_a_changed_file_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "f.json"
    path.write_text("{}", encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    check_hash(path, digest)
    path.write_text("{ }", encoding="utf-8")
    with pytest.raises(ValueError, match="frozen one"):
        check_hash(path, digest)


def test_the_confirmation_plan_uses_only_unsimulated_blocks(root: Path) -> None:
    from vishwaroop.sim.collect import load_plan

    plan = load_plan(root / "evals" / "M1-confirmation-plan.json")
    blocks = {
        seed // 1000
        for family in plan["families"]
        for seed in range(family["first_seed"], family["first_seed"] + family["count"])
    }
    assert blocks == {4, 9}
