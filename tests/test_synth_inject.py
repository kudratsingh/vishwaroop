"""ET-M3-1's six injections on FABRICATED frames (a red square cube, a green disc goal), each
checked to change what it should, and to be rejected by the checker while its source passes."""

from __future__ import annotations

import hashlib
import math
import random
from typing import Any

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")

from fake_scene import (  # noqa: E402
    BACKGROUND,
    CUBE_PX,
    GREEN,
    PROJECTION,
    draw,
    episode_frames,
    manifest,
)
from vishwaroop.synth.checker import (  # noqa: E402
    Tolerances,
    check_candidate,
    credited,
    cube_area,
    measure,
    reference,
)
from vishwaroop.synth.inject import (  # noqa: E402
    DUPLICATE_OFFSETS,
    InjectionError,
    break_hash,
    choose_offset,
    goal_pixel_shift,
    inject,
    injection_plan,
    injection_seed,
    remove_object,
    resize_object,
    ring_colour,
)
from vishwaroop.synth.masks import green_mask, red_mask  # noqa: E402

TOL = Tolerances(
    a_lo=0.8,
    a_hi=1.25,
    merge_radius_px=20.0,
    first_frame_tolerance=0.0,
    goal_centroid_px=3.0,
    min_green_pixels=100,
)
OTHER = draw((100, 400), (400, 100))
CUBE_AREA = CUBE_PX * CUBE_PX


def source(seed: int, steps: int = 8) -> tuple[list[Any], dict[str, Any]]:
    return episode_frames(steps), manifest(seed)


def checked(frames: list[Any], candidate: dict[str, Any], seed: int) -> Any:
    snapshot_render = episode_frames()[0]
    ref = reference(manifest(seed), measure(snapshot_render), snapshot_render.shape, TOL)
    return check_candidate(candidate, frames, ref, snapshot_render, TOL)


def build(t: int, i: int) -> tuple[Any, list[Any]]:
    seed = injection_seed(t, i)
    frames, candidate = source(seed)
    return inject(t, i, frames, candidate, projection=PROJECTION, other_render=OTHER), frames


def digest(frames: list[Any]) -> str:
    return hashlib.sha256(b"".join(frame.tobytes() for frame in frames)).hexdigest()


def test_the_injection_seeds_are_the_frozen_ones() -> None:
    assert injection_seed(1, 0) == 10100
    assert injection_seed(3, 4) == 10124
    assert injection_seed(6, 9) == 10159
    plan = injection_plan()
    assert [seed for _, _, seed in plan] == list(range(10100, 10160))
    with pytest.raises(ValueError):
        injection_seed(7, 0)
    with pytest.raises(ValueError):
        injection_seed(1, 10)


@pytest.mark.parametrize("t", range(1, 7))
def test_the_first_draw_is_the_step_and_earlier_frames_are_untouched(t: int) -> None:
    injection, frames = build(t, 0)
    step = random.Random(injection.seed).randrange(1, len(frames) - 1)
    assert injection.detail["step"] == step >= 1
    if t != 6:
        assert all(injection.frames[k] is frames[k] for k in range(step))


def test_every_injection_leaves_its_source_unmodified() -> None:
    for t, i, seed in injection_plan():
        frames, candidate = source(seed)
        before = (digest(frames), repr(candidate))
        inject(t, i, frames, candidate, projection=PROJECTION, other_render=OTHER)
        assert (digest(frames), repr(candidate)) == before


def test_every_injection_is_rejected_and_every_source_passes() -> None:
    for t, i, seed in injection_plan():
        frames, candidate = source(seed)
        original = checked(frames, candidate, seed)
        injection = inject(t, i, frames, candidate, projection=PROJECTION, other_render=OTHER)
        result = checked(injection.frames, injection.manifest, seed)
        assert original.passed, (t, i, original.to_json())
        assert credited(original.passed, result.passed), (t, i, injection.detail)


def test_a_control_passes() -> None:
    frames, candidate = source(10000)
    assert checked(frames, candidate, 10000).passed


def test_object_removed_fills_the_cube_with_the_ring_median() -> None:
    injection, frames = build(1, 3)
    step = injection.detail["step"]
    for k in range(step, len(frames)):
        assert not red_mask(injection.frames[k]).any()
        rows, cols = np.nonzero(red_mask(frames[k]))
        assert (injection.frames[k][rows, cols] == BACKGROUND).all()
    result = checked(injection.frames, injection.manifest, injection.seed)
    assert result.to_json()["failed_checks"] == ["cube_area"]
    assert result.failed["cube_area"]["frame"] == step


def test_the_ring_falls_back_to_6_to_12_px_when_the_near_ring_is_too_small() -> None:
    frame = draw(None, None)
    frame[194:230, 194:230] = GREEN  # covers the 1 to 6 px ring of the cube below
    frame[200:224, 200:224] = (200, 20, 20)
    frame[188:194, 188:236] = (50, 50, 50)  # part of the 6 to 12 px ring, darker
    mask = red_mask(frame)
    colour = ring_colour(frame, mask)
    assert tuple(colour) == BACKGROUND
    near = draw((200, 200), None)
    near[193:200, 190:240] = (60, 61, 62)  # most of the 1 to 6 px ring above the cube
    near[224:231, 190:240] = (60, 61, 62)
    near[193:231, 193:200] = (60, 61, 62)
    near[193:231, 224:231] = (60, 61, 62)
    assert tuple(ring_colour(near, red_mask(near))) == (60, 61, 62)
    assert not red_mask(remove_object(near)).any()


def test_object_duplicated_uses_the_first_free_offset_and_keeps_it() -> None:
    injection, frames = build(2, 0)
    assert tuple(injection.detail["offset"]) == DUPLICATE_OFFSETS[0]
    step = injection.detail["step"]
    for k in range(step, len(frames)):
        assert int(red_mask(injection.frames[k]).sum()) == 2 * CUBE_AREA
        moved = np.roll(red_mask(frames[k]), DUPLICATE_OFFSETS[0], axis=(0, 1))
        assert (red_mask(injection.frames[k]) >= moved).all()
    result = checked(injection.frames, injection.manifest, injection.seed)
    assert result.to_json()["failed_checks"] == ["extra_red"]
    blocked = draw((300, 200), (310, 270))  # the goal sits where (0, +60) would land
    assert choose_offset(blocked) == DUPLICATE_OFFSETS[1]
    edge = draw((10, 10), None)  # only offsets that stay in the image and are free count
    assert choose_offset(edge) == (0, 60)
    corner = draw((0, 490), None)
    corner[:, :] = (200, 20, 20)
    with pytest.raises(InjectionError, match="no duplicate offset"):
        choose_offset(corner)


@pytest.mark.parametrize("i", [0, 1, 2, 5])
def test_cube_resized_scales_the_area_about_the_centroid(i: int) -> None:
    injection, frames = build(3, i)
    rng = random.Random(injection.seed)
    rng.randrange(1, len(frames) - 1)
    factor = rng.choice([0.6, 1.6])
    assert injection.detail["factor"] == factor
    step = injection.detail["step"]
    before = measure(frames[step]).red[0]
    after = measure(injection.frames[step]).red[0]
    assert after[0] / before[0] == pytest.approx(factor**2, rel=0.12)
    assert after[1] == pytest.approx(before[1], abs=1.0)
    assert after[2] == pytest.approx(before[2], abs=1.0)
    result = checked(injection.frames, injection.manifest, injection.seed)
    assert "cube_area" in result.to_json()["failed_checks"]


def test_resizing_only_pastes_the_resized_mask() -> None:
    frame = draw((200, 200), None)
    frame[200:212, 200:212] = (90, 90, 90)  # an L-shaped cube: one quadrant is background
    out = resize_object(frame, 1.6)
    area = int(red_mask(out).sum())
    assert area == pytest.approx(int(red_mask(frame).sum()) * 2.56, rel=0.12)
    assert not red_mask(out)[195:205, 195:205].any()


@pytest.mark.parametrize("i", [0, 3, 6, 9])
def test_goal_moved_in_the_manifest(i: int) -> None:
    injection, frames = build(4, i)
    rng = random.Random(injection.seed)
    rng.randrange(1, len(frames) - 1)
    distance, angle = rng.uniform(0.03, 0.06), rng.uniform(0, 2 * math.pi)
    old = manifest(injection.seed)["goal_position"]
    new = injection.manifest["goal_position"]
    assert new[0] == pytest.approx(old[0] + distance * math.cos(angle))
    assert new[1] == pytest.approx(old[1] + distance * math.sin(angle))
    assert new[2] == old[2]
    assert math.dist(new[:2], old[:2]) == pytest.approx(distance)
    assert all(a is b for a, b in zip(injection.frames, frames, strict=True))
    assert checked(injection.frames, injection.manifest, injection.seed).to_json()[
        "failed_checks"
    ] == ["manifest"]


@pytest.mark.parametrize(
    ("i", "field", "value"),
    [
        (1, "task_id", "PickCube-v1"),
        (4, "task_version", "m0-1-changed"),
        (7, "task_id", "PickCube-v1"),
    ],
)
def test_task_changed_in_the_manifest(i: int, field: str, value: str) -> None:
    injection, frames = build(4, i)
    assert all(a is b for a, b in zip(injection.frames, frames, strict=True))
    assert injection.manifest[field] == value
    others = {key: val for key, val in injection.manifest.items() if key != field}
    assert others == {key: val for key, val in manifest(injection.seed).items() if key != field}
    assert checked(injection.frames, injection.manifest, injection.seed).to_json()[
        "failed_checks"
    ] == ["manifest"]


@pytest.mark.parametrize("i", [2, 5, 8])
def test_goal_pixels_shift_by_the_projected_goal_move(i: int) -> None:
    injection, frames = build(4, i)
    rng = random.Random(injection.seed)
    rng.randrange(1, len(frames) - 1)
    distance, angle = rng.uniform(0.03, 0.06), rng.uniform(0, 2 * math.pi)
    expected = (
        math.floor(1000 * distance * math.sin(angle) + 0.5),
        math.floor(1000 * distance * math.cos(angle) + 0.5),
    )
    assert tuple(injection.detail["shift"]) == expected
    step = injection.detail["step"]
    before = measure(frames[step]).green_centroid
    after = measure(injection.frames[step]).green_centroid
    assert before is not None and after is not None
    assert after[0] - before[0] == pytest.approx(expected[0], abs=1.0)
    assert after[1] - before[1] == pytest.approx(expected[1], abs=1.0)
    assert injection.manifest == manifest(injection.seed)
    assert int(green_mask(injection.frames[step]).sum()) <= int(green_mask(frames[step]).sum())
    result = checked(injection.frames, injection.manifest, injection.seed)
    assert result.to_json()["failed_checks"] == ["goal_centroid"]


def test_goal_pixel_shift_uses_the_projection() -> None:
    assert goal_pixel_shift(PROJECTION, [0.0, 0.0, 0.05], 0.05, 0.0) == (0, 50)
    assert goal_pixel_shift(PROJECTION, [0.0, 0.0, 0.05], 0.04, math.pi / 2) == (40, 0)
    with pytest.raises(InjectionError, match="projection"):
        inject(4, 2, *source(injection_seed(4, 2)))


@pytest.mark.parametrize("i", range(10))
def test_asset_hash_broken_changes_one_first_hex_digit(i: int) -> None:
    injection, frames = build(5, i)
    old = manifest(injection.seed)["asset_sha256s"]
    new = injection.manifest["asset_sha256s"]
    rng = random.Random(injection.seed)
    rng.randrange(1, len(frames) - 1)
    index = rng.randrange(len(old))
    assert injection.detail["asset_index"] == index
    changed = [k for k in range(len(old)) if old[k] != new[k]]
    assert changed == [index]
    assert new[index][1:] == old[index][1:] and new[index][0] != old[index][0]
    assert new[index][0] in "0123456789abcdef"
    assert break_hash("f" + "0" * 63)[0] == "0"
    assert checked(injection.frames, injection.manifest, injection.seed).to_json()[
        "failed_checks"
    ] == ["manifest"]


def test_initial_render_mismatch_replaces_frame_0_only() -> None:
    injection, frames = build(6, 0)
    assert injection.detail["render_seed"] == injection.seed + 500
    assert (injection.frames[0] == OTHER).all()
    assert all(injection.frames[k] is frames[k] for k in range(1, len(frames)))
    result = checked(injection.frames, injection.manifest, injection.seed)
    assert "first_frame" in result.to_json()["failed_checks"]
    with pytest.raises(InjectionError, match="seed \\+ 500"):
        inject(6, 0, *source(injection_seed(6, 0)))


def test_injections_that_cannot_be_built_are_refused() -> None:
    frames, candidate = source(injection_seed(1, 0), steps=1)
    with pytest.raises(InjectionError, match="T >= 2"):
        inject(1, 0, frames, candidate)
    frames, candidate = source(10000)
    with pytest.raises(InjectionError, match="seed"):
        inject(1, 0, frames, candidate)
    seed = injection_seed(2, 0)
    empty = [draw(None, (150, 350)) for _ in range(9)]
    with pytest.raises(InjectionError, match="no red pixel"):
        inject(2, 0, empty, manifest(seed))


def test_merge_radius_decides_between_area_and_extra_red() -> None:
    frame = draw((300, 200), None)
    frame[300:324, 240:264] = (200, 20, 20)
    stats = measure(frame)
    assert cube_area(stats, 20.0) == (CUBE_AREA, CUBE_AREA)
    assert cube_area(stats, 50.0) == (2 * CUBE_AREA, 0)
