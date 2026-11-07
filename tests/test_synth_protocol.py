"""M3's seed blocks, partitions and identities (evals/M3-protocol.md sections 2 and 5). No data."""

from __future__ import annotations

import pytest

from vishwaroop.synth.protocol import (
    ProtocolRefusalError,
    block_of,
    check_family_seed,
    check_training_seeds,
    family_id,
    family_partition,
    partition_for_seed,
    scene_group_id,
)


@pytest.mark.parametrize(
    ("seed", "partition"),
    [(10000, "train"), (12345, "train"), (15999, "train"), (16000, "dev"), (17999, "dev")],
)
def test_m3_blocks_have_their_frozen_partition(seed: int, partition: str) -> None:
    assert partition_for_seed(seed) == partition


@pytest.mark.parametrize("seed", [0, 7003, 8000, 9999])
def test_blocks_0_to_9_get_no_new_m3_data(seed: int) -> None:
    with pytest.raises(ProtocolRefusalError, match="never uses blocks 0 to 9"):
        partition_for_seed(seed)
    with pytest.raises(ProtocolRefusalError):
        scene_group_id(seed)


@pytest.mark.parametrize("seed", [18000, 18500, 19999])
def test_reserved_blocks_are_never_simulated(seed: int) -> None:
    with pytest.raises(ProtocolRefusalError, match="reserved"):
        partition_for_seed(seed)


@pytest.mark.parametrize("seed", [20000, -1, True, 10000.0])
def test_seeds_outside_the_blocks_or_not_integers_are_refused(seed: object) -> None:
    with pytest.raises(ProtocolRefusalError):
        partition_for_seed(seed)  # type: ignore[arg-type]


def test_scene_group_id_names_the_block() -> None:
    assert scene_group_id(10900) == "m3-seed-block-10"
    assert scene_group_id(16042) == "m3-seed-block-16"
    assert block_of(11999) == 11


def test_a_training_set_may_hold_m0_and_m3_train_seeds() -> None:
    seeds = [0, 7999, 10000, 15999]
    assert check_training_seeds(seeds) == seeds


@pytest.mark.parametrize("seed", [8000, 9500, 16000, 17999])
def test_a_dev_seed_in_a_training_set_is_refused(seed: int) -> None:
    with pytest.raises(ProtocolRefusalError, match="dev block"):
        check_training_seeds([10000, seed])


@pytest.mark.parametrize("seed", [18000, 19999, 20000])
def test_a_reserved_or_unknown_seed_in_a_training_set_is_refused(seed: int) -> None:
    with pytest.raises(ProtocolRefusalError):
        check_training_seeds([seed])


def test_family_ids_follow_section_5() -> None:
    assert family_id("synth", "lateral-miss") == "m3-synth-lateral-miss"
    assert family_id("eval", "missed-grasp") == "m3-eval-missed-grasp"
    assert family_partition("m3-synth-close-high") == "train"
    assert family_partition("m3-eval-missed-grasp") == "dev"
    for kind, name in (("op", "x"), ("synth", "Lateral"), ("synth", "a_b"), ("eval", "")):
        with pytest.raises(ProtocolRefusalError):
            family_id(kind, name)
    with pytest.raises(ProtocolRefusalError):
        family_partition("m0-scripted-missed-grasp")


def test_a_family_lies_wholly_in_one_partition() -> None:
    check_family_seed("m3-synth-lateral-miss", 11000)
    check_family_seed("m3-eval-missed-grasp", 16000)
    with pytest.raises(ProtocolRefusalError, match="wholly"):
        check_family_seed("m3-synth-lateral-miss", 16000)
    with pytest.raises(ProtocolRefusalError, match="wholly"):
        check_family_seed("m3-eval-missed-grasp", 11000)
