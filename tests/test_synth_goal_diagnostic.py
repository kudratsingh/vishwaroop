"""The goal-check diagnostic's helpers and one pass over FABRICATED scenes (no real seed)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("numpy")
pytest.importorskip("scipy")
pytest.importorskip("PIL")

from fake_scene import FakeSceneEnv
from vishwaroop.synth import goal_diagnostic as gd

TASK = ("PickCubeSO100-v1", "m0-1", 200)


def test_helpers() -> None:
    assert gd.whole_pixels((1.5, -1.5)) == (2, -1)
    assert gd.injected_drift((3.0, 4.0), [(-3, -4), (10, 0)]) == (0.0, 0)
    assert gd.injected_drift((0.0, 0.0), [(6, 8), (0, 12)]) == (10.0, 0)
    assert gd.bin_of(0.0) == "[0.0, 0.25)"
    assert gd.bin_of(0.9) == "[0.9, 0.95)"
    assert gd.bin_of(1.2) == ">= 1.0"
    assert gd.longest_ineligible([True, False, False, True, False]) == {"length": 2, "start": 1}
    assert gd.longest_ineligible([True]) == {"length": 0, "start": -1}


def test_one_pass_over_fabricated_scenes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gd, "SEQUENCES", {"fake": (10936,)})
    monkeypatch.setattr(gd, "FOCUS", (10936, 2))
    env: Any = FakeSceneEnv()
    episodes = gd.run_episodes(env, TASK, tmp_path / "images")
    assert (tmp_path / "images" / "seed-10936-frame-2.png").exists()
    frames = episodes[0]["frames"]
    assert frames[0]["drift"] == pytest.approx(0.0)
    assert all(
        row["injected_drift_measured"] == pytest.approx(row["injected_drift_computed"], abs=0.5)
        for row in frames
    )
    summary = gd.summarize(episodes)
    cell = summary["by_threshold"]["0.9"]
    assert cell["eligible_frames"] == len(frames)
    assert cell["stop_9_would_hold"] is False
    assert cell["eligible_frames_a_shift_could_pass_computed"] == 0
    assert gd.focus(episodes)["visibility"] == pytest.approx(1.0)
