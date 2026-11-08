"""ET-M3-6's training sets and evaluation windows (WO-022), as ``evals/M3-exit-tests.json``
freezes them. No torch here: selection, counts and refusals are plain Python; F1 uses numpy.

- Base fit set: M0's train partition minus all 30 ``m0-scripted-missed-grasp`` episodes and minus
  the 23 episodes with seed divisible by 10 of the other six families (the no-harm holdout, never
  trained on): 207 episodes and 31,031 windows (WINDOW 14, stride 1), in manifest order. Any other
  count stops the run before training.
- F_star: the 27 missed-grasp train episodes whose seed is not divisible by 10: 4,161 windows.
- F1: ``default_rng(1)``; ``idx = rng.integers(0, 31031, 4161)`` into the base windows; then
  noise of sd 0.05 x the base ``state_std`` on the conditioning states (window steps 0 to 3;
  joint_position and object_position only), then noise of sd 0.05 x the base ``action_std`` on
  every action; targets, target_position and object_grasped unchanged.
- F2 and F1s: the recorded block-11 episodes in their recording's order, truncated from the last
  episode's end to exactly W* windows.

Every loader refuses an imagined record, a record carrying a ``generator_model_artifact``, and a
``generated`` validation status (groundwork for ET-M3-5, which this claims nothing about), and every
training set refuses a dev or reserved seed (``synth.protocol.check_training_seeds``).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from ..synth.m3_record import EVAL_FAMILY, NOMINAL_FAMILY, OPERATOR_FAMILIES, check_seed
from ..synth.protocol import (
    ProtocolRefusalError,
    block_of,
    check_training_seeds,
    family_partition,
)
from .pilot_data import STATE_SIZE, EpisodeArrays, read_episode

M0_MANIFEST = Path("artifacts/manifests/m0-dataset-v1.json")
M0_MANIFEST_SHA256 = "267d77ead98119715350f0fc82987e715f7ce41a4d0337401b7469206711b9c7"
TARGET_FAMILY = "m0-scripted-missed-grasp"
HOLDOUT_EVERY = 10
HISTORY, HORIZON = 3, 10
WINDOW = HISTORY + HORIZON + 1
BASE_EPISODES = 207
BASE_WINDOWS = 31031
NO_HARM_EPISODES = 23
F_STAR_EPISODES = 27
W_STAR = 4161
EVAL_EPISODES = 60
EVAL_BLOCK = 16
F1_RNG_SEED = 1
F1_NOISE_SD = 0.05
CONDITIONING_STEPS = HISTORY + 1  # window steps 0 to 3
NOISED_STATE_DIMS = 9  # joint_position (0:6) and object_position (6:9)
ARMS = ("F0", "F_star", "F1", "F1s", "F2")
OUT_OF_SCOPE_ARMS = ("F3",)


class DataRefusalError(ValueError):
    """A record, count or set that ET-M3-6's frozen data rules refuse; nothing is trained."""


def check_record(manifest: dict[str, Any], where: str) -> None:
    """Refuse an imagined record, a generator's, or one with a ``generated`` status."""
    kind = manifest.get("environment_kind")
    if kind != "physics_sim":
        raise DataRefusalError(f"{where}: environment_kind {kind!r}; only physics_sim is read")
    provenance = manifest.get("provenance") or {}
    if provenance.get("generator_model_artifact") is not None:
        raise DataRefusalError(f"{where}: carries a generator_model_artifact")
    statuses = (manifest.get("validation") or {}).get("statuses") or []
    if "generated" in statuses:
        raise DataRefusalError(f"{where}: has a generated status")


def read_manifest(path: Path, expected_sha256: str | None = None) -> dict[str, Any]:
    """An episode's ``episode.json``, checked against ``expected_sha256`` when given."""
    raw = (Path(path) / "episode.json").read_bytes()
    if expected_sha256 is not None:
        actual = hashlib.sha256(raw).hexdigest()
        if actual != expected_sha256:
            raise DataRefusalError(f"{path}: episode.json sha256 {actual}, not {expected_sha256}")
    manifest: dict[str, Any] = json.loads(raw)
    check_record(manifest, str(path))
    return manifest


def windows_in(episode: EpisodeArrays) -> int:
    """Stride-1 windows of ``WINDOW`` states, as ``compute_pilot._Data._windows`` cuts them."""
    return max(len(episode.states) - WINDOW + 1, 0)


@dataclass(frozen=True)
class M0Split:
    """M0's train entries, by ET-M3-6's rule, each list in manifest order."""

    base: list[dict[str, Any]]
    no_harm: list[dict[str, Any]]
    f_star: list[dict[str, Any]]
    excluded_target: list[dict[str, Any]]


def m0_train_entries(
    manifest_path: Path = M0_MANIFEST, root: Path = Path()
) -> list[dict[str, Any]]:
    """M0's train entries in manifest order, after the manifest's frozen sha256 and every entry's
    record are checked."""
    raw = (Path(root) / manifest_path).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != M0_MANIFEST_SHA256:
        raise DataRefusalError(f"{manifest_path} sha256 {digest}, not {M0_MANIFEST_SHA256}")
    entries = [entry for entry in json.loads(raw)["episodes"] if entry["partition"] == "train"]
    check_training_seeds(entry["seed"] for entry in entries)
    for entry in entries:
        read_manifest(Path(root) / entry["path"], entry.get("episode_sha256"))
    return entries


def split_m0(entries: Sequence[dict[str, Any]]) -> M0Split:
    """Base, no-harm holdout, F_star and the three excluded target episodes, in manifest order."""
    base: list[dict[str, Any]] = []
    no_harm: list[dict[str, Any]] = []
    f_star: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for entry in entries:
        if entry["partition"] != "train":
            raise DataRefusalError(f"{entry['episode_id']} is not a train episode")
        held = entry["seed"] % HOLDOUT_EVERY == 0
        if entry["family"] == TARGET_FAMILY:
            (excluded if held else f_star).append(entry)
        else:
            (no_harm if held else base).append(entry)
    return M0Split(base, no_harm, f_star, excluded)


def _is_base(episode: EpisodeArrays) -> bool:
    return episode.family != TARGET_FAMILY and episode.seed % HOLDOUT_EVERY != 0


def _is_no_harm(episode: EpisodeArrays) -> bool:
    return episode.family != TARGET_FAMILY and episode.seed % HOLDOUT_EVERY == 0


def check_base(base: Sequence[EpisodeArrays]) -> int:
    """Refuse any base other than 207 episodes and 31,031 windows; returns the window count."""
    windows = sum(windows_in(item) for item in base)
    if len(base) != BASE_EPISODES or windows != BASE_WINDOWS:
        raise DataRefusalError(
            f"base fit set has {len(base)} episodes and {windows} windows, not the frozen "
            f"{BASE_EPISODES} and {BASE_WINDOWS}; stopped before training"
        )
    check_training_seeds(item.seed for item in base)
    return windows


def base_split(
    episodes: Sequence[EpisodeArrays],
) -> tuple[list[EpisodeArrays], list[EpisodeArrays]]:
    """``compute_pilot._Data``'s split for ET-M3-6: (base fit set, no-harm holdout), both in
    manifest order, refused unless the base is 207 episodes and 31,031 windows and the holdout 23
    episodes. ``_Data`` then computes its normalization statistics on the base alone."""
    base = [item for item in episodes if _is_base(item)]
    no_harm = [item for item in episodes if _is_no_harm(item)]
    check_base(base)
    if len(no_harm) != NO_HARM_EPISODES:
        raise DataRefusalError(f"{len(no_harm)} no-harm episodes, not {NO_HARM_EPISODES}")
    return base, no_harm


def f_star_episodes(episodes: Sequence[EpisodeArrays]) -> list[EpisodeArrays]:
    """The 27 missed-grasp train episodes with seed not divisible by 10, giving 4,161 windows."""
    chosen = [
        item for item in episodes if item.family == TARGET_FAMILY and item.seed % HOLDOUT_EVERY != 0
    ]
    windows = sum(windows_in(item) for item in chosen)
    if len(chosen) != F_STAR_EPISODES or windows != W_STAR:
        raise DataRefusalError(
            f"F_star has {len(chosen)} episodes and {windows} windows, not "
            f"{F_STAR_EPISODES} and {W_STAR}"
        )
    check_training_seeds(item.seed for item in chosen)
    return chosen


def _m3_episode(
    item: dict[str, Any], families: Iterable[str], root: Path, partition: str
) -> EpisodeArrays:
    """One recorded M3 episode, checked against its recording's listing and its own manifest."""
    path = Path(root) / item["path"]
    if "episode_json_sha256" not in item:
        raise DataRefusalError(f"{path}: the recording did not pin its gated episode.json sha256")
    manifest = read_manifest(path, item["episode_json_sha256"])
    family = manifest["policy"]["family_id"]
    seed = int(item["seed"])
    if family not in set(families) or family != item["family"]:
        raise DataRefusalError(f"{path}: family {family} is not one of {sorted(families)}")
    if manifest["split"]["partition"] != partition or family_partition(family) != partition:
        raise DataRefusalError(
            f"{path}: partition {manifest['split']['partition']}, not {partition}"
        )
    if manifest["episode_id"] != f"{family}-seed-{seed:06d}":
        raise DataRefusalError(f"{path}: episode id {manifest['episode_id']} is not seed {seed}'s")
    transitions = manifest["data"]["transitions_artifact"]
    episode = read_episode(path, transitions["sha256"], seed)
    return replace(episode, family=family)


def load_m3_train(
    kept: Sequence[dict[str, Any]], families: Iterable[str], root: Path = Path()
) -> list[EpisodeArrays]:
    """A recording's kept episodes, in order, as training data: block 11 only. Unlike
    ``pilot_data.load_train`` it does not refuse seeds of 8000 and up, since M3's train blocks are
    10 to 15; ``check_training_seeds`` refuses every dev and reserved seed instead, and
    ``m3_record.check_seed`` then refuses a seed held for ET-M3-1, a block-10 seed, and any seed
    off its family's block (WO-022 records its training families on block 11 only), whoever
    recorded the episode."""
    check_training_seeds(int(item["seed"]) for item in kept)
    for item in kept:
        check_seed(str(item["family"]), int(item["seed"]))
    names = tuple(families)
    return [_m3_episode(item, names, root, "train") for item in kept]


def load_m3_eval(kept: Sequence[dict[str, Any]], root: Path = Path()) -> list[EpisodeArrays]:
    """The evaluation family's 60 gated episodes, in order: block 16 and its family only."""
    if len(kept) != EVAL_EPISODES:
        raise DataRefusalError(f"{len(kept)} evaluation episodes, not {EVAL_EPISODES}")
    for item in kept:
        if block_of(int(item["seed"])) != EVAL_BLOCK:
            raise ProtocolRefusalError(f"evaluation seed {item['seed']} is not in block 16")
    return [_m3_episode(item, (EVAL_FAMILY,), root, "dev") for item in kept]


def truncate_counts(
    episodes: Sequence[EpisodeArrays], target: int = W_STAR
) -> tuple[list[int], bool]:
    """How many windows each episode adds, in order, the last cut from its end so the total is
    exactly ``target``; and whether ``target`` was reached. Refuses an episode past the one that
    reaches ``target``: the recording stops there."""
    used = []
    total = 0
    for index, item in enumerate(episodes):
        if total >= target:
            raise DataRefusalError(f"episode {index} comes after the windows reached {target}")
        take = min(windows_in(item), target - total)
        used.append(take)
        total += take
    return used, total == target


# The families of F2 and F1s.
F2_FAMILIES = OPERATOR_FAMILIES
F1S_FAMILIES = (NOMINAL_FAMILY,)


def windows_array(episodes: Sequence[EpisodeArrays], counts: Sequence[int] | None = None) -> Any:
    """Stride-1 windows as float64 numpy arrays, (n, 14, 13) states and (n, 13, 6) actions, in
    episode order; ``counts`` keeps only each episode's first windows."""
    import numpy as np

    states, actions = [], []
    for index, item in enumerate(episodes):
        s = np.asarray(item.states, dtype=np.float64)
        a = np.asarray(item.actions, dtype=np.float64)
        n = windows_in(item) if counts is None else counts[index]
        for start in range(n):
            states.append(s[start : start + WINDOW])
            actions.append(a[start : start + WINDOW - 1])
    if not states:
        raise DataRefusalError("no windows")
    return np.stack(states), np.stack(actions)


def f1_augment(base_states: Any, base_actions: Any, state_std: Any, action_std: Any) -> Any:
    """F1's W* augmented windows, exactly as frozen, drawn once and shared by every seed.

    ``rng = numpy.random.default_rng(1)``; ``idx = rng.integers(0, 31031, 4161)``; then one
    ``rng.normal`` draw of shape (4161, 4, 9), sd 0.05 x the base ``state_std`` of each dimension,
    added to window steps 0 to 3 of joint_position and object_position; then one of shape
    (4161, 13, 6), sd 0.05 x the base ``action_std``, added to every action. Draws are in C order
    (window, step, dimension). Target states, target_position and object_grasped are unchanged.
    Returns float64 states, actions and ``idx``.
    """
    import numpy as np

    states = np.asarray(base_states, dtype=np.float64)
    actions = np.asarray(base_actions, dtype=np.float64)
    if len(states) != BASE_WINDOWS or len(actions) != BASE_WINDOWS:
        raise DataRefusalError(f"F1 draws from {BASE_WINDOWS} base windows, not {len(states)}")
    state_scale = F1_NOISE_SD * np.asarray(state_std, dtype=np.float64)[:NOISED_STATE_DIMS]
    action_scale = F1_NOISE_SD * np.asarray(action_std, dtype=np.float64)
    if state_scale.shape != (NOISED_STATE_DIMS,) or states.shape[2] != STATE_SIZE:
        raise DataRefusalError("state_std must cover the 13 state values")
    rng = np.random.default_rng(F1_RNG_SEED)
    idx = rng.integers(0, BASE_WINDOWS, W_STAR)
    chosen_states = states[idx].copy()
    chosen_actions = actions[idx].copy()
    steps = CONDITIONING_STEPS
    state_noise = rng.normal(0.0, state_scale, size=(W_STAR, steps, NOISED_STATE_DIMS))
    action_noise = rng.normal(0.0, action_scale, size=(W_STAR, *chosen_actions.shape[1:]))
    chosen_states[:, :steps, :NOISED_STATE_DIMS] += state_noise
    chosen_actions += action_noise
    return chosen_states, chosen_actions, idx


def array_digest(*arrays: Any) -> str:
    """sha256 over arrays' shapes, dtypes and C-order bytes, to show a set is the same each time."""
    import numpy as np

    digest = hashlib.sha256()
    for array in arrays:
        value = np.ascontiguousarray(array)
        digest.update(f"{value.shape}{value.dtype}".encode())
        digest.update(value.tobytes())
    return digest.hexdigest()


def check_arm(arm: str) -> str:
    """Refuse F3 (out of WO-022's scope) and any arm ET-M3-6 does not name."""
    if arm in OUT_OF_SCOPE_ARMS:
        raise DataRefusalError(f"arm {arm} needs a generator; it is out of WO-022's scope")
    if arm not in ARMS:
        raise DataRefusalError(f"unknown arm {arm}; ET-M3-6's physics arms are {ARMS}")
    return arm
