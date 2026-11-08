"""WO-022's refusals, the gate's verdict and the recording sequences; no numpy, no simulator.

Recorders, gates, replay reports, approvals and run directories here are FABRICATED; nothing here
is evidence for any exit test.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import pytest

from vishwaroop.models.compute_pilot import WINDOW as PILOT_WINDOW
from vishwaroop.sim.baseline import VARIANTS, PlanSettings
from vishwaroop.sim.replay import RepeatResult, ReplayReport, ReplayTolerance
from vishwaroop.synth import et_m3_6_record as rec
from vishwaroop.synth.et_m3_6_guard import (
    FROZEN,
    GuardRefusalError,
    check_frozen,
    check_not_run,
    check_not_started,
    check_resume,
    require_owner_approval,
)
from vishwaroop.synth.m3_gate import (
    REPLAY_UNDECIDED_REASON,
    UNDECIDED_REPEATS_PASS,
    GateResult,
    GateSpecificationError,
    decide,
    gate_tolerance,
)
from vishwaroop.synth.m3_record import (
    CLOSE_HIGH_FAMILY,
    EVAL_FAMILY,
    LATERAL_FAMILY,
    NOMINAL_FAMILY,
    Recorded,
    check_seed,
)
from vishwaroop.synth.protocol import ET_M3_1_HELD_SEEDS, ProtocolRefusalError

ROOT = Path(__file__).resolve().parents[1]
STREAMS = ["joint_position", "object_position", "target_position"]
TOLERANCE = ReplayTolerance(STREAMS, 0.001, 3, 200)


# --- frozen files, approvals, one run ---------------------------------------------------------


def test_the_frozen_files_have_their_frozen_hashes() -> None:
    digests = check_frozen(root=ROOT)
    assert set(digests) == {str(path) for path in FROZEN}


def test_a_changed_frozen_file_is_refused(tmp_path: Path) -> None:
    (tmp_path / "evals").mkdir()
    (tmp_path / "evals" / "x.json").write_text("{}")
    with pytest.raises(GuardRefusalError, match="not the frozen"):
        check_frozen({Path("evals/x.json"): "0" * 64}, root=tmp_path)


def _approvals(tmp_path: Path, *records: dict[str, Any]) -> Path:
    path = tmp_path / "approvals.jsonl"
    path.write_text("".join(json.dumps(record) + "\n" for record in records))
    return path


def test_recording_waits_for_an_owner_approval_naming_wo_022(tmp_path: Path) -> None:
    ledger = _approvals(
        tmp_path,
        {"record_id": "a-1", "approver": "owner", "gate": "ET-M3-1 hold"},
        {"record_id": "a-2", "approver": "owner", "gate": "WO-022 recordings, agent details"},
        {"record_id": "a-3", "approver": "agent", "gate": "WO-022"},
    )
    with pytest.raises(GuardRefusalError, match="required"):
        require_owner_approval(None, ("WO-022",), ledger)
    with pytest.raises(GuardRefusalError, match="does not mention"):
        require_owner_approval("a-1", ("WO-022",), ledger)
    with pytest.raises(GuardRefusalError, match="not the owner"):
        require_owner_approval("a-3", ("WO-022",), ledger)
    with pytest.raises(GuardRefusalError, match="no approvals record"):
        require_owner_approval("a-9", ("WO-022",), ledger)
    assert require_owner_approval("a-2", ("WO-022",), ledger)["record_id"] == "a-2"


def test_scoring_needs_an_approval_naming_et_m3_6_scoring(tmp_path: Path) -> None:
    ledger = _approvals(
        tmp_path,
        {"record_id": "s-1", "approver": "owner", "gate": "WO-022 recordings"},
        {"record_id": "s-2", "approver": "owner", "gate": "ET-M3-6 scoring of physics arms"},
    )
    with pytest.raises(GuardRefusalError, match="does not mention"):
        require_owner_approval("s-1", ("ET-M3-6", "scoring"), ledger)
    require_owner_approval("s-2", ("ET-M3-6", "scoring"), ledger)


def test_the_repository_has_no_wo_022_approval_yet() -> None:
    """Nothing is recorded before the owner answers: no record in the real ledger names WO-022."""
    ledger = ROOT / "ledgers" / "approvals.jsonl"
    records = [json.loads(line) for line in ledger.read_text().splitlines() if line]
    if any("wo-022" in str(record.get("gate", "")).lower() for record in records):
        pytest.skip("an owner approval naming WO-022 exists; this guard test no longer applies")
    for record in records:
        with pytest.raises(GuardRefusalError):
            require_owner_approval(record["record_id"], ("WO-022",), ledger)


def test_a_second_result_and_a_fresh_restart_are_refused(tmp_path: Path) -> None:
    run = tmp_path / "20261108T000000Z_aaaaaaaa"
    run.mkdir()
    check_not_run(tmp_path, rec.result_name("eval"))
    (run / rec.result_name("eval")).write_text("{}")
    with pytest.raises(GuardRefusalError, match="already run"):
        check_not_run(tmp_path, rec.result_name("eval"))
    (run / rec.plan_name("f2")).write_text("{}")
    with pytest.raises(GuardRefusalError, match="resume it"):
        check_not_started(tmp_path, rec.plan_name("f2"), None)
    check_not_started(tmp_path, rec.plan_name("f2"), run)
    with pytest.raises(GuardRefusalError, match="no et_m3_6_f1s"):
        check_not_started(tmp_path, rec.plan_name("f1s"), run)


def test_a_partial_result_counts_as_run(tmp_path: Path) -> None:
    run = tmp_path / "r"
    run.mkdir()
    (run / f"{rec.result_name('eval')}.partial").write_text("")
    with pytest.raises(GuardRefusalError):
        check_not_run(tmp_path, rec.result_name("eval"))


def test_resume_refuses_other_settings_or_code() -> None:
    plan = {"config": {"kind": "eval"}, "commit": "abc"}
    check_resume(plan, {"kind": "eval"}, code_changed=False)
    with pytest.raises(GuardRefusalError, match="settings differ"):
        check_resume(plan, {"kind": "f2"}, code_changed=False)
    with pytest.raises(GuardRefusalError, match="code under src"):
        check_resume(plan, {"kind": "eval"}, code_changed=True)


# --- seeds ------------------------------------------------------------------------------------


@pytest.mark.parametrize("family", [LATERAL_FAMILY, CLOSE_HIGH_FAMILY, NOMINAL_FAMILY])
def test_every_held_seed_is_refused(family: str) -> None:
    for held in ET_M3_1_HELD_SEEDS:
        for seed in (held[0], held[-1]):
            with pytest.raises(ProtocolRefusalError, match="held for ET-M3-1"):
                check_seed(family, seed)


def test_block_10_is_refused_even_for_unheld_seeds() -> None:
    for seed in (10000, 10059, 10900, 10999):
        with pytest.raises(ProtocolRefusalError, match="block 10"):
            check_seed(LATERAL_FAMILY, seed)


@pytest.mark.parametrize("seed", [18000, 18999, 19000, 19999])
@pytest.mark.parametrize("family", [EVAL_FAMILY, LATERAL_FAMILY, NOMINAL_FAMILY])
def test_reserved_blocks_are_refused(family: str, seed: int) -> None:
    with pytest.raises(ProtocolRefusalError, match="reserved"):
        check_seed(family, seed)


def test_each_family_stays_on_its_block() -> None:
    check_seed(EVAL_FAMILY, 16000)
    check_seed(LATERAL_FAMILY, 11000)
    check_seed(NOMINAL_FAMILY, 11999)
    for family, seed in (
        (EVAL_FAMILY, 17000),  # dev, but the ET-M3-3 suite's block
        (EVAL_FAMILY, 11000),  # train
        (LATERAL_FAMILY, 16000),  # dev
        (LATERAL_FAMILY, 12000),  # train, but not block 11
        (CLOSE_HIGH_FAMILY, 7000),  # M0's
        ("m3-synth-wrong-place", 11000),  # not a WO-022 family
    ):
        with pytest.raises(ProtocolRefusalError):
            check_seed(family, seed)


def test_the_seed_ranges_are_the_frozen_ones() -> None:
    assert list(rec.EVAL_SEEDS) == list(range(16000, 16100))
    assert rec.F2_SEEDS[0] == 11000 and rec.F2_SEEDS[-1] == 11999
    assert (
        rec.EVAL_SETTINGS == VARIANTS["missed-grasp"] == PlanSettings(grasp_offset_xy_m=(-0.04, 0))
    )
    assert rec.WINDOW == PILOT_WINDOW == 14
    assert rec.windows_of(20) == 8 and rec.windows_of(12) == 0 and rec.windows_of(13) == 1


# --- the gate's verdict -----------------------------------------------------------------------


def _report(
    deviations: list[float],
    labels: list[str],
    recorded: str = "never_lifted",
    valid: bool | None = None,
    reason: str = "",
) -> ReplayReport:
    repeats = [
        RepeatResult(i, d, 3, "joint_position", label, False, [])
        for i, (d, label) in enumerate(zip(deviations, labels, strict=True))
    ]
    ok = all(d <= 0.001 for d in deviations) and all(label == recorded for label in labels)
    if valid is None:
        valid = ok and recorded != "insufficient_evidence"
    return ReplayReport("ep", "initial_state_only", valid, reason, recorded, 15, TOLERANCE, repeats)


def test_the_gate_passes_three_faithful_repeats() -> None:
    result = decide(_report([0.0, 0.0005, 0.001], ["never_lifted"] * 3))
    assert result.passed and not result.undecided


def test_the_gate_rejects_a_replay_past_the_tolerance() -> None:
    result = decide(_report([0.0, 0.0010001, 0.0], ["never_lifted"] * 3, reason="dev"))
    assert not result.passed and "deviated" in result.reason


def test_the_gate_rejects_a_non_finite_deviation() -> None:
    result = decide(_report([0.0, float("nan"), 0.0], ["never_lifted"] * 3, reason="nan"))
    assert not result.passed
    assert result.to_json()["max_deviations"][1] == "nan"


def test_the_gate_rejects_a_label_that_changes_between_repeats() -> None:
    labels = ["outside_target", "still_grasped", "outside_target"]
    result = decide(_report([0.0] * 3, labels, recorded="outside_target", reason="label"))
    assert not result.passed and "still_grasped" in result.reason


def test_the_gate_needs_exactly_three_repeats() -> None:
    assert not decide(_report([0.0] * 2, ["never_lifted"] * 2)).passed


def test_an_undecided_label_repeated_identically_passes_by_agent_detail_1() -> None:
    assert UNDECIDED_REPEATS_PASS is True
    report = _report(
        [0.0] * 3,
        ["insufficient_evidence"] * 3,
        recorded="insufficient_evidence",
        reason=REPLAY_UNDECIDED_REASON,
    )
    assert decide(report).passed and decide(report).undecided
    vetoed = decide(report, undecided_pass=False)
    assert not vetoed.passed and "vetoed" in vetoed.reason


def test_an_undecided_label_still_fails_for_any_other_reason() -> None:
    report = _report(
        [0.0] * 3,
        ["insufficient_evidence"] * 3,
        recorded="insufficient_evidence",
        reason="state was restored 2 times over 3 repeats",
    )
    assert not decide(report).passed


def test_the_gate_tolerance_is_m0s_with_the_m3_protocol(tmp_path: Path) -> None:
    tolerance, rubric = gate_tolerance(ROOT / "evals" / "M0-exit-tests.json")
    assert tolerance.repeats == 3 and tolerance.max_state_deviation == 0.001
    assert tolerance.compare_streams == STREAMS
    assert tolerance.protocol_version is not None and tolerance.protocol_version.startswith("m3-")
    assert rubric.rubric_version == "m0-place-1"
    frozen = json.loads((ROOT / "evals" / "M0-exit-tests.json").read_text())
    frozen["replay"]["repeats"] = 2
    changed = tmp_path / "m0.json"
    changed.write_text(json.dumps(frozen))
    with pytest.raises(GateSpecificationError):
        gate_tolerance(changed)


# --- recording sequences, with a FABRICATED recorder and gate ---------------------------------


class _Fakes:
    """A recorder that writes nothing and a gate that fails the listed seeds."""

    def __init__(self, tmp_path: Path, failing: set[int], steps: int = 1000) -> None:
        self.tmp_path = tmp_path
        self.failing = failing
        self.steps = steps
        self.recorded: list[tuple[str, int, PlanSettings]] = []

    def recorder(self, _env: Any, family: str, seed: int, settings: PlanSettings, *_: Any) -> Any:
        self.recorded.append((family, seed, settings))
        path = self.tmp_path / f"{family}-seed-{seed:06d}"
        return Recorded(path, path.name, seed, family, self.steps, "never_lifted", None, "x", True)

    def gate(self, path: Path, *_: Any) -> GateResult:
        seed = int(path.name.rsplit("-", 1)[1])
        passed = seed not in self.failing
        reason = "ok" if passed else "repeat 1 deviated"
        return GateResult(path.name, passed, reason, "never_lifted", [], [], False)


def _run(sequence: Any, fakes: _Fakes, progress: Path) -> dict[str, Any]:
    return rec.run_sequence(
        sequence,
        env=None,  # type: ignore[arg-type]
        out=fakes.tmp_path,
        run_id="run",
        task=None,  # type: ignore[arg-type]
        rubric=None,  # type: ignore[arg-type]
        tolerance=TOLERANCE,
        progress=progress,
        recorder=fakes.recorder,
        gate=fakes.gate,
    )


def test_the_evaluation_family_stops_at_60_passing_and_lists_the_skipped(tmp_path: Path) -> None:
    fakes = _Fakes(tmp_path, failing={16003, 16010})
    outcome = _run(rec.eval_sequence(), fakes, tmp_path / "p.jsonl")
    assert outcome["complete"] and len(outcome["kept"]) == 60
    assert [line["seed"] for line in outcome["skipped"]] == [16003, 16010]
    assert outcome["kept"][-1]["seed"] == 16061
    assert all(settings == VARIANTS["missed-grasp"] for _, _, settings in fakes.recorded)
    assert {family for family, _, _ in fakes.recorded} == {EVAL_FAMILY}
    summary = rec.summary("eval", outcome)
    assert "label" not in summary["kept"][0] and "windows" not in summary["kept"][0]
    assert summary["skipped"] == [
        {"seed": 16003, "family": EVAL_FAMILY, "reason": "repeat 1 deviated"},
        {"seed": 16010, "family": EVAL_FAMILY, "reason": "repeat 1 deviated"},
    ]


def test_the_evaluation_family_stops_when_16099_is_reached(tmp_path: Path) -> None:
    fakes = _Fakes(tmp_path, failing=set(range(16000, 16041)))
    outcome = _run(rec.eval_sequence(), fakes, tmp_path / "p.jsonl")
    assert not outcome["complete"] and len(outcome["kept"]) == 59
    assert max(seed for _, seed, _ in fakes.recorded) == 16099


def test_f2_alternates_over_kept_episodes_only(tmp_path: Path) -> None:
    fakes = _Fakes(tmp_path, failing={11001, 11002}, steps=1012)  # 1000 windows each
    outcome = _run(rec.f2_sequence(), fakes, tmp_path / "p.jsonl")
    kept = outcome["kept"]
    assert outcome["complete"] and [line["seed"] for line in kept] == [
        11000,
        11003,
        11004,
        11005,
        11006,
    ]
    operators = [line["settings"]["operator"] for line in kept]
    assert operators == ["lateral-miss", "close-high", "lateral-miss", "close-high", "lateral-miss"]
    assert [line["settings"].get("s") for line in kept if "s" in line["settings"]] == [1, -1, 1]
    assert [line["settings"].get("k") for line in kept if "k" in line["settings"]] == [1, 2, 3]
    # the skipped scenes were tried with the operator the kept count asked for
    tried = {seed: family for family, seed, _ in fakes.recorded}
    assert tried[11001] == tried[11002] == CLOSE_HIGH_FAMILY
    for family, seed, settings in fakes.recorded:
        if family == LATERAL_FAMILY:
            d = random.Random(seed).uniform(0.02, 0.05)
            assert abs(settings.grasp_offset_xy_m[1]) == pytest.approx(d, abs=0)
            assert settings.grasp_offset_xy_m[0] == 0.0
        else:
            assert settings.grasp_height_m == 0.012 + random.Random(seed).uniform(0.02, 0.04)
    summary = rec.summary("f2", outcome)
    assert summary["windows_total"] == 5000 and summary["windows_used_total"] == rec.W_STAR
    assert [item["windows_used"] for item in summary["kept"]] == [1000, 1000, 1000, 1000, 161]


def test_f2_stops_when_block_11_runs_out(tmp_path: Path) -> None:
    fakes = _Fakes(tmp_path, failing=set(), steps=13)  # one window each
    outcome = _run(rec.f2_sequence(), fakes, tmp_path / "p.jsonl")
    assert not outcome["complete"] and len(outcome["kept"]) == 1000


def test_f1s_follows_f2s_scenes_skips_failures_and_reports_unmatched(tmp_path: Path) -> None:
    scenes = [11000, 11003, 11004, 11005, 11006]
    fakes = _Fakes(tmp_path, failing={11003}, steps=1012)
    outcome = _run(rec.f1s_sequence(scenes), fakes, tmp_path / "p.jsonl")
    assert [line["seed"] for line in outcome["kept"]] == [11000, 11004, 11005, 11006]
    assert [line["seed"] for line in outcome["skipped"]] == [11003]
    assert not outcome["complete"]  # 4,000 windows < W*: unmatched
    assert all(s == VARIANTS["nominal"] and f == NOMINAL_FAMILY for f, _, s in fakes.recorded)


def test_a_stopped_sequence_resumes_without_repeating_a_seed(tmp_path: Path) -> None:
    progress = tmp_path / "p.jsonl"
    first = _Fakes(tmp_path, failing={11001}, steps=1012)
    sequence = rec.f2_sequence()
    calls = 0
    first_recorder = first.recorder

    def interrupting(*args: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 4:
            raise KeyboardInterrupt
        return first_recorder(*args)

    first.recorder = interrupting  # type: ignore[method-assign]
    with pytest.raises(KeyboardInterrupt):
        _run(sequence, first, progress)
    assert [line["seed"] for line in rec.read_lines(progress)] == [11000, 11001, 11002]
    second = _Fakes(tmp_path, failing={11001}, steps=1012)
    outcome = _run(sequence, second, progress)
    assert [seed for _, seed, _ in second.recorded] == [11003, 11004, 11005]
    uninterrupted = _run(sequence, _Fakes(tmp_path, {11001}, 1012), tmp_path / "q.jsonl")
    assert [line["settings"] for line in outcome["kept"]] == [
        line["settings"] for line in uninterrupted["kept"]
    ]


def test_a_progress_log_out_of_order_is_refused(tmp_path: Path) -> None:
    progress = tmp_path / "p.jsonl"
    progress.write_text(json.dumps({"seed": 11001, "kept": True}) + "\n")
    with pytest.raises(GuardRefusalError, match="prefix"):
        _run(rec.f2_sequence(), _Fakes(tmp_path, set()), progress)


def test_f1s_needs_one_completed_f2_and_eval_needs_no_training(tmp_path: Path) -> None:
    with pytest.raises(GuardRefusalError, match="0 et_m3_6_f2"):
        rec.sequence_for("f1s", tmp_path)
    run = tmp_path / "r1"
    run.mkdir()
    (run / rec.result_name("f2")).write_text(json.dumps({"complete": False, "kept": []}))
    with pytest.raises(GuardRefusalError, match="stopped"):
        rec.sequence_for("f1s", tmp_path)
    rec.sequence_for("eval", tmp_path)
    (run / "et_m3_6_train_F0_seed-0.plan.json").write_text("{}")
    with pytest.raises(GuardRefusalError, match="evaluation family comes first"):
        rec.sequence_for("eval", tmp_path)


# --- the command lines refuse before any simulator or training --------------------------------


def _owner(tmp_path: Path, gate: str) -> Path:
    return _approvals(tmp_path, {"record_id": "ok-1", "approver": "owner", "gate": gate})


def test_recording_without_an_approval_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(ROOT)
    assert rec.main(["eval"]) == 2
    assert rec.main(["f2", "--owner-approval", "approvals-not-a-record"]) == 2


def test_a_second_recording_of_the_evaluation_family_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(ROOT)
    runs = tmp_path / "runs"
    (runs / "r1").mkdir(parents=True)
    (runs / "r1" / rec.result_name("eval")).write_text("{}")
    monkeypatch.setattr(rec, "RUNS", runs)
    monkeypatch.setattr(rec, "APPROVALS", _owner(tmp_path, "WO-022 recordings"))
    assert rec.main(["eval", "--owner-approval", "ok-1"]) == 2
    assert "already run" in capsys.readouterr().err


def test_a_started_evaluation_family_is_resumed_not_restarted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(ROOT)
    runs = tmp_path / "runs"
    (runs / "r1").mkdir(parents=True)
    (runs / "r1" / rec.plan_name("eval")).write_text("{}")
    monkeypatch.setattr(rec, "RUNS", runs)
    monkeypatch.setattr(rec, "APPROVALS", _owner(tmp_path, "WO-022 recordings"))
    assert rec.main(["eval", "--owner-approval", "ok-1"]) == 2
    assert "resume it" in capsys.readouterr().err


def test_training_refuses_f3_a_second_training_and_a_missing_evaluation_family(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from vishwaroop.models import et_m3_6_train as train

    monkeypatch.chdir(ROOT)
    runs = tmp_path / "runs"
    (runs / "r1").mkdir(parents=True)
    monkeypatch.setattr(train, "RUNS", runs)
    assert train.main(["--arm", "F3", "--seed", "0"]) == 2
    assert "out of WO-022's scope" in capsys.readouterr().err
    assert train.main(["--arm", "F0", "--seed", "3"]) == 2
    assert train.main(["--arm", "F0", "--seed", "0"]) == 2
    assert "0 et_m3_6_eval.json results" in capsys.readouterr().err
    (runs / "r1" / train.result_name("F1", 2)).write_text("{}")
    assert train.main(["--arm", "F1", "--seed", "2"]) == 2
    assert "already run" in capsys.readouterr().err
    (runs / "r1" / train.plan_name("F2", 1)).write_text("{}")
    assert train.main(["--arm", "F2", "--seed", "1"]) == 2
    assert "resume it" in capsys.readouterr().err


def test_scoring_without_an_et_m3_6_scoring_approval_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from vishwaroop.models import et_m3_6_score as scoring

    monkeypatch.chdir(ROOT)
    monkeypatch.setattr(scoring, "APPROVALS", _owner(tmp_path, "WO-022 recordings"))
    monkeypatch.setattr(scoring, "RUNS", tmp_path / "runs")
    assert scoring.main([]) == 2
    assert scoring.main(["--owner-approval", "ok-1"]) == 2
    assert "does not mention" in capsys.readouterr().err
    monkeypatch.setattr(scoring, "APPROVALS", _owner(tmp_path, "ET-M3-6 scoring"))
    (tmp_path / "runs" / "r1").mkdir(parents=True)
    (tmp_path / "runs" / "r1" / scoring.RESULT).write_text("{}")
    assert scoring.main(["--owner-approval", "ok-1"]) == 2
    assert "already run" in capsys.readouterr().err
