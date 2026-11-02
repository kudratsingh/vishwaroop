"""Score the dev-informed refinement against plain A, once, on fresh confirmation data.

    python -m vishwaroop.models.m1_confirm

Run it from the repository root, in the robotics environment. The rule is frozen in
``evals/M1-refinement-accept.json`` and the data planned in ``evals/M1-confirmation-plan.json``,
both before the data existed. It refuses a changed rule or manifest, an episode outside the plan's
seed blocks, and a second run once a result exists. Exit codes: 0 scored, whichever design wins;
2 refused.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import time
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..sim.runlog import ledgered_run, require_code_root
from .compute_pilot import HISTORY, _Data, _machine, _stats_of, _torch
from .cube_study import EPOCHS, SEEDS, VARIANTS, _baseline_predictions, _Kinematics, phase_masks
from .family_sweep import SEED_HOLDOUT
from .m1_evaluate import ENSEMBLE_RUN, TRAIN_MANIFEST, _ensemble_on, _load_ensemble, _Windows
from .m1_followups import BEFORE, NEVER_HELD, STAYS_PUT, _cube_by_phase
from .pilot_data import EpisodeArrays, read_episode, split_holdout

RULE_PATH = Path("evals/M1-refinement-accept.json")
RULE_SHA256 = "29c75e389e6b1924036c36bb37d42e0ee01748975d071242dba6f1e7d243ac01"
MANIFEST = Path("artifacts/manifests/m1-confirmation-v1.json")
MANIFEST_SHA256 = "5e6097320145f815c75494a6742228fd27c4346baf4d721cb5be4bd26627657d"
ALLOWED_BLOCKS = (4, 9)
RESULT = "m1_confirm.json"
PURPOSE = "WO-005 stage 0: the refinement against plain A, once, on fresh data"
PLAIN_A = "carry-contact-beta-fall-still-reach"
REFINEMENT = "carry-contact-beta-fall-still-onset"
TIE_M = 1e-9


def check_hash(path: Path, expected: str) -> bytes:
    raw = path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected:
        raise ValueError(f"{path} has sha256 {actual}, and the frozen one is {expected}")
    return raw


def check_not_run(runs_root: Path) -> None:
    found = sorted(runs_root.glob(f"*/{RESULT}*"))
    if found:
        raise ValueError(f"already scored in {found[0]}; the rule allows one scoring")


def load_confirmation(manifest: dict[str, Any], root: Path) -> list[EpisodeArrays]:
    """Every episode of the confirmation set, refused if any lies outside the fresh blocks."""
    episodes = []
    for entry in manifest["episodes"]:
        if entry["seed"] // 1000 not in ALLOWED_BLOCKS:
            raise ValueError(f"{entry['episode_id']}: seed {entry['seed']} is not in a fresh block")
        episode = read_episode(root / entry["path"], entry["transitions_sha256"], entry["seed"])
        episodes.append(replace(episode, family=entry["family"]))
    if not episodes:
        raise ValueError("the confirmation set is empty")
    return sorted(episodes, key=lambda item: (item.family, item.seed))


def accepts(
    held_refined: Sequence[float],
    held_plain: Sequence[float],
    free_refined: Sequence[float],
    free_plain: Sequence[float],
) -> bool:
    """The frozen rule for one seed: held lower at every horizon, free never higher."""
    if not (len(held_refined) == len(held_plain) == len(free_refined) == len(free_plain)):
        raise ValueError("horizons differ")
    lower = all(a < b - TIE_M for a, b in zip(held_refined, held_plain, strict=True))
    not_worse = all(a <= b + TIE_M for a, b in zip(free_refined, free_plain, strict=True))
    return lower and not_worse


def _group_tables(
    predictions: dict[str, Any], truth: Any, masks: dict[str, Any], chosen: Any
) -> dict[str, Any]:
    picked = {name: mask[chosen] for name, mask in masks.items()}
    return {
        name: _cube_by_phase(value[chosen], truth[chosen], picked)
        for name, value in predictions.items()
    }


def _score(device: str) -> dict[str, Any]:
    torch = _torch()
    manifest = json.loads(check_hash(MANIFEST, MANIFEST_SHA256))
    episodes = load_confirmation(manifest, Path())
    data = _Data(TRAIN_MANIFEST, device, split_holdout)
    stats = {**_stats_of(data), "kinematics": _Kinematics(device)}
    windows = _Windows(episodes, device)
    view = copy.copy(data)
    view.holdout_s, view.holdout_a = windows.states, windows.actions
    truth = windows.states[:, HISTORY + 1 :]
    masks = phase_masks(episodes, len(windows.states), device)
    with torch.no_grad():
        stays_put = _baseline_predictions(view, stats)[STAYS_PUT]
    labels = windows.episode.cpu().tolist()
    dev_group = torch.tensor(
        ["-dev-" in windows.families[i] for i in labels], dtype=torch.bool, device=device
    )
    groups = {
        "all": torch.ones_like(dev_group),
        "train_families_block_4": ~dev_group,
        "dev_families_block_9": dev_group,
    }
    cells: dict[str, Any] = {}
    for seed in SEEDS:
        print(f"seed {seed}", file=sys.stderr, flush=True)
        path = ENSEMBLE_RUN / "work" / SEED_HOLDOUT / BEFORE / f"seed-{seed}" / "checkpoint.pt"
        layers = _load_ensemble(path, device, EPOCHS)
        predictions = {STAYS_PUT: stays_put}
        for name in (BEFORE, PLAIN_A, REFINEMENT):
            predictions[name], _ = _ensemble_on(
                stats, VARIANTS[name], layers, windows.states, windows.actions
            )
        tables = {
            group: _group_tables(predictions, truth, masks, chosen)
            for group, chosen in groups.items()
        }
        every = tables["all"]
        cells[str(seed)] = {
            "cube_rmse_by_phase": tables,
            "accepted": accepts(
                every[REFINEMENT]["held"],
                every[PLAIN_A]["held"],
                every[REFINEMENT]["never_held"],
                every[PLAIN_A]["never_held"],
            ),
        }
    return {
        "episodes": len(episodes),
        "windows": len(windows.states),
        "windows_by_phase": {name: int(mask.sum().item()) for name, mask in masks.items()},
        "free_phases": list(NEVER_HELD),
        "seeds": cells,
        "refinement_kept": all(cell["accepted"] for cell in cells.values()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", choices=("mps", "cpu"), default="mps")
    args = parser.parse_args(argv)
    try:
        require_code_root()
        check_hash(RULE_PATH, RULE_SHA256)
        check_not_run(Path("runs"))
        machine = _machine()
        with ledgered_run(
            purpose=PURPOSE,
            config={"rule_sha256": RULE_SHA256, "manifest_sha256": MANIFEST_SHA256},
            seeds={"none": 0},
            env_lock={"machine": machine},
        ) as run:
            if run.dirty:
                raise ValueError("commit first, so the code note stays true")
            started = time.perf_counter()
            report: dict[str, Any] = {
                "run": run.directory.name,
                "code": run.code_note,
                "machine": machine,
                "rule_sha256": RULE_SHA256,
                "manifest_sha256": MANIFEST_SHA256,
                **_score(args.device),
            }
            report["seconds"] = time.perf_counter() - started
            text = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
            partial_file = run.directory / f"{RESULT}.partial"
            partial_file.write_text(text, encoding="utf-8")
            partial_file.replace(run.directory / RESULT)
            run.note = f"refinement kept: {report['refinement_kept']}"
            print(run.directory)
    except (ValueError, OSError, KeyError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
