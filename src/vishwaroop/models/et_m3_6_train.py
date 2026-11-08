"""Train one ET-M3-6 arm on one seed (WO-022), with WO-004's model and every hyperparameter of
``runs/20261102T041509Z_93dd348c``: ``carry-contact-beta-fall``, 30 epochs, a 3-member ensemble
seeded by the arm's seed (0, 1 or 2), ``cube_study._train`` unchanged.

    python -m vishwaroop.models.et_m3_6_train --arm F0 --seed 0 --owner-approval <record_id>

Run it from the repository root, in the robotics environment, at a clean commit, after the
evaluation family is recorded (and F2's or F1s's recording, for those arms). It refuses unless
``--owner-approval`` names the owner's record that ``et_m3_6_guard.TRAINING`` lists, which is
recorded in the run's ledger config and its result. It trains on the Mac's MPS only: the owner's
approved scope is local Mac MPS training, and WO-004's run, whose hyperparameters every arm matches,
used MPS, so arms trained on different devices are never compared (``--device`` is not offered,
and scoring checks every training's device). It refuses F3, a dev seed in a training set, a base
other than 207 episodes and 31,031 windows, and a second training of the same arm on the same seed.
Every epoch is saved; a stopped training is continued with ``--resume-from <its first run>`` from
its last completed epoch (AGENTS.md section 13.9), with the same settings and code. Normalization
statistics are ``compute_pilot._Data``'s on the base alone; an arm's windows are the base windows
in manifest order, then its added windows in order.

Exit codes: 0 trained, 2 refused.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

from ..sim.runlog import ledgered_run, require_code_root
from ..synth.et_m3_6_guard import (
    APPROVALS,
    RUNS,
    STATUS,
    TRAINING,
    GuardRefusalError,
    check_frozen,
    check_not_run,
    check_not_started,
    check_resume,
    code_changed,
    require_owner_approval,
    write_once,
)
from ..synth.et_m3_6_record import find_result
from .compute_pilot import WINDOW, _Data, _machine, _stats_of, _torch
from .et_m3_6_data import (
    BASE_EPISODES,
    BASE_WINDOWS,
    F1S_FAMILIES,
    F2_FAMILIES,
    M0_MANIFEST,
    W_STAR,
    DataRefusalError,
    array_digest,
    audit_recordings,
    base_split,
    check_arm,
    f1_augment,
    f_star_episodes,
    load_m3_train,
    m0_train_entries,
    truncate_counts,
    windows_array,
)
from .pilot_data import load_train

TRAINED_VARIANT = "carry-contact-beta-fall"
EPOCHS = 30
SEEDS = (0, 1, 2)
WO004_RUN = "runs/20261102T041509Z_93dd348c"
# WO-004's device and the owner's approved scope (local Mac MPS training); every arm uses it.
DEVICE = "mps"


def result_name(arm: str, seed: int) -> str:
    return f"et_m3_6_train_{arm}_seed-{seed}.json"


def plan_name(arm: str, seed: int) -> str:
    return f"et_m3_6_train_{arm}_seed-{seed}.plan.json"


def check_seed(seed: int) -> int:
    if seed not in SEEDS:
        raise GuardRefusalError(f"seed {seed} is not one of ET-M3-6's {SEEDS}")
    return seed


def stats_digest(stats: dict[str, Any]) -> str:
    """sha256 of the six normalization statistics' values, so every arm shows it used the same."""
    names = ("state_mean", "state_std", "delta_std", "lag", "action_mean", "action_std")
    values = {name: stats[name].detach().cpu().double().tolist() for name in names}
    text = json.dumps(values, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def prerequisites(arm: str, runs_root: Path = RUNS) -> dict[str, Any]:
    """The recordings an arm needs: the evaluation family always (it is recorded before any arm is
    trained), F2's for F2, F1s's for F1s."""
    needed: dict[str, Any] = {"eval": find_result("eval", runs_root)}
    if arm == "F2":
        needed["f2"] = find_result("f2", runs_root)
    if arm == "F1s":
        needed["f1s"] = find_result("f1s", runs_root)
    return needed


def added_windows(
    arm: str, data: Any, recordings: dict[str, Any], root: Path = Path()
) -> tuple[Any, Any, dict[str, Any]]:
    """The arm's added windows as float32 tensors on the data's device, and what they are."""
    torch = _torch()
    empty = (data.windows_s[:0], data.windows_a[:0])
    info: dict[str, Any]
    if arm == "F0":
        return *empty, {"episodes": [], "windows": 0}
    if arm == "F_star":
        chosen = f_star_episodes(load_train(M0_MANIFEST, root))
        states, actions = windows_array(chosen)
        info = {"episodes": [f"{item.family}-seed-{item.seed:06d}" for item in chosen]}
    elif arm == "F1":
        # idx indexes the base windows exactly as trained: _Data's, in manifest order
        base_s = data.windows_s[:BASE_WINDOWS].cpu().double().numpy()
        base_a = data.windows_a[:BASE_WINDOWS].cpu().double().numpy()
        state_std = data.state_std.cpu().double().numpy()
        action_std = data.action_std.cpu().double().numpy()
        states, actions, idx = f1_augment(base_s, base_a, state_std, action_std)
        info = {"episodes": [], "idx_sha256": array_digest(idx)}
    else:
        key, families = ("f2", F2_FAMILIES) if arm == "F2" else ("f1s", F1S_FAMILIES)
        kept = recordings[key]["kept"]
        episodes = load_m3_train(kept, families, root)
        counts, matched = truncate_counts(episodes)
        if not matched and arm == "F2":
            raise DataRefusalError(f"F2 adds {sum(counts)} windows, not W* = {W_STAR}")
        states, actions = windows_array(episodes, counts)
        info = {
            "episodes": [item["episode_id"] for item in kept],
            "windows_by_episode": counts,
            "matched": matched,
        }
    s = torch.tensor(states, dtype=torch.float32).to(data.device)
    a = torch.tensor(actions, dtype=torch.float32).to(data.device)
    info.update(windows=len(s), windows_sha256=array_digest(s.cpu().numpy(), a.cpu().numpy()))
    if arm in ("F_star", "F1") and len(s) != W_STAR:
        raise DataRefusalError(f"{arm} adds {len(s)} windows, not W* = {W_STAR}")
    return s, a, info


def arm_data(arm: str, device: str, recordings: dict[str, Any], root: Path = Path()) -> Any:
    """``_Data`` on the base fit set, with the arm's windows: base windows, then added ones."""
    torch = _torch()
    m0_train_entries(M0_MANIFEST, root)  # the frozen manifest, and no imagined or generated record
    data = _Data(M0_MANIFEST, device, base_split)
    if data.fit_episodes != BASE_EPISODES or len(data.windows_s) != BASE_WINDOWS:
        raise DataRefusalError(
            f"base has {data.fit_episodes} episodes and {len(data.windows_s)} windows; stopped"
        )
    added_s, added_a, info = added_windows(arm, data, recordings, root)
    data.windows_s = torch.cat([data.windows_s, added_s])
    data.windows_a = torch.cat([data.windows_a, added_a])
    info.update(base_episodes=data.fit_episodes, base_windows=BASE_WINDOWS)
    info["total_windows"] = len(data.windows_s)
    return data, info


def checkpoint_record(checkpoint: Path) -> dict[str, str]:
    """The saved checkpoint's path and sha256, as the result records them (owner, 2026-11-08)."""
    return {
        "checkpoint": str(checkpoint),
        "checkpoint_sha256": hashlib.sha256(Path(checkpoint).read_bytes()).hexdigest(),
    }


def check_same_data(
    arm: str, seed: int, info: dict[str, Any], stats_sha256: str, runs_root: Path = RUNS
) -> None:
    """Every seed of an arm trains on the same windows (F1's are "drawn once and shared by all
    seeds"): refuse unless this seed's added-window digest, episodes and normalization digest equal
    those of every earlier seed's result for the arm."""
    for other in range(3):
        if other == seed:
            continue
        for path in sorted(Path(runs_root).glob(f"*/{result_name(arm, other)}")):
            done = json.loads(path.read_text(encoding="utf-8"))
            for key in ("windows_sha256", "episodes", "total_windows"):
                if done["data"].get(key) != info.get(key):
                    raise GuardRefusalError(
                        f"arm {arm} seed {seed}: {key} differs from seed {other}'s ({path})"
                    )
            if done["stats_sha256"] != stats_sha256:
                raise GuardRefusalError(
                    f"arm {arm} seed {seed}: normalization differs from seed {other}'s ({path})"
                )


def _device() -> str:
    """The one training device, ``DEVICE``; refused when this machine has no MPS."""
    torch = _torch()
    if not torch.backends.mps.is_available():
        raise GuardRefusalError(
            f"{DEVICE} is not available; every ET-M3-6 arm trains on {DEVICE} (WO-004's device, "
            "the owner's approved scope), so nothing is trained here"
        )
    return DEVICE


def _run(args: argparse.Namespace) -> int:
    from .cube_study import VARIANTS, _Kinematics, _train

    frozen = check_frozen()
    approval = require_owner_approval(args.owner_approval, TRAINING, APPROVALS, STATUS)
    arm = check_arm(args.arm)
    seed = check_seed(args.seed)
    check_not_run(RUNS, result_name(arm, seed))
    check_not_started(RUNS, plan_name(arm, seed), args.resume_from)
    recordings = prerequisites(arm, RUNS)
    device = _device()
    config = {
        "arm": arm,
        "seed": seed,
        "variant": TRAINED_VARIANT,
        "epochs": EPOCHS,
        "device": device,
        "hyperparameters_from": WO004_RUN,
        "window": WINDOW,
        "frozen": frozen,
    }
    machine = _machine()
    with ledgered_run(
        purpose=f"WO-022: ET-M3-6 arm {arm}, seed {seed}",
        config={
            **config,
            "owner_approval": approval["record_id"],
            "resume_from": str(args.resume_from),
        },
        seeds={"torch": seed},
        env_lock={"machine": machine},
    ) as run:
        if run.dirty:
            raise GuardRefusalError("commit first, so the code note stays true")
        if args.resume_from is None:
            home = run.directory
            write_once(home / plan_name(arm, seed), {"config": config, "commit": run.commit})
        else:
            home = Path(args.resume_from)
            plan = json.loads((home / plan_name(arm, seed)).read_text(encoding="utf-8"))
            check_resume(plan, config, code_changed(plan["commit"]))
        work = home / "work" / f"{arm}-seed-{seed}"
        work.mkdir(parents=True, exist_ok=True)
        audit = audit_recordings(recordings)
        data, info = arm_data(arm, device, recordings)
        stats = {**_stats_of(data), "kinematics": _Kinematics(device)}
        check_same_data(arm, seed, info, stats_digest(stats), RUNS)
        started = time.perf_counter()
        checkpoint = work / "checkpoint.pt"
        _, training = _train(data, stats, VARIANTS[TRAINED_VARIANT], seed, EPOCHS, checkpoint)
        report = {
            "run": run.directory.name,
            "started_in": home.name,
            "code": run.code_note,
            "machine": machine,
            "owner_approval": approval["record_id"],
            **config,
            **checkpoint_record(checkpoint),
            "stats_sha256": stats_digest(stats),
            "training": training,
            "data": info,
            "split_audit": audit,
            "seconds_this_process": time.perf_counter() - started,
        }
        write_once(run.directory / result_name(arm, seed), report)
        run.note = f"arm {arm} seed {seed}: {info['total_windows']} windows, {EPOCHS} epochs"
        print(run.directory)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--owner-approval", default=None, help="approvals record id")
    parser.add_argument("--resume-from", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        require_code_root()
        return _run(args)
    except (ValueError, OSError, KeyError) as exc:
        print(f"refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
