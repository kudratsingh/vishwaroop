"""Repository tools: status ledger/board, append-only check, secrets scan, links, hashes, budget."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import budget_preflight
import check_hashes
import check_immutable
import check_links
import scan_secrets
import status_board

# ----------------------------------------------------------------------------- status board


def _mini_repo(tmp_path: Path, root: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "work_orders").mkdir(parents=True)
    (repo / "config").mkdir()
    shutil.copy(root / "config" / "phases.json", repo / "config" / "phases.json")
    phases = json.loads((repo / "config" / "phases.json").read_text())
    first_phase = phases["phases"][0]["id"]
    (repo / "work_orders" / "WO-001-demo.md").write_text(
        f"# WO-001 | Demo work order\n**Phase:** {first_phase}\n**Exit tests advanced:** none\n"
    )
    return repo


def test_status_ledger_validates_transitions(tmp_path: Path, root: Path) -> None:
    repo = _mini_repo(tmp_path, root)
    ledger = repo / "work_orders" / "STATUS.jsonl"
    phases = repo / "config" / "phases.json"
    kw = {"ledger": ledger, "phases_path": phases, "root": repo}
    status_board.append({"wo": "WO-001", "event": "ready"}, **kw)
    status_board.append({"wo": "WO-001", "event": "in_progress"}, **kw)
    with pytest.raises(status_board.StatusError, match="cannot go from in_progress to ready"):
        status_board.append({"wo": "WO-001", "event": "ready"}, **kw)
    with pytest.raises(status_board.StatusError, match="requires --report and --commit"):
        status_board.append({"wo": "WO-001", "event": "accepted"}, **kw)
    status_board.append(
        {"wo": "WO-001", "event": "accepted", "report": "reports/WO-001.md", "commit": "abc"}, **kw
    )
    with pytest.raises(status_board.StatusError, match="cannot go from accepted"):
        status_board.append({"wo": "WO-001", "event": "in_progress"}, **kw)
    with pytest.raises(status_board.StatusError, match="unknown work order"):
        status_board.append({"wo": "WO-999", "event": "ready"}, **kw)
    # ledger is append-only: the three successful appends, in order; refused events wrote nothing
    assert len(ledger.read_text().splitlines()) == 3


def test_phase_and_exit_test_events(tmp_path: Path, root: Path) -> None:
    repo = _mini_repo(tmp_path, root)
    ledger = repo / "work_orders" / "STATUS.jsonl"
    phases_path = repo / "config" / "phases.json"
    kw = {"ledger": ledger, "phases_path": phases_path, "root": repo}
    cfg = json.loads(phases_path.read_text())
    phase = cfg["phases"][0]["id"]
    et = cfg["phases"][0]["exit_tests"][0]["id"]
    with pytest.raises(status_board.StatusError, match="cannot go from not_started to in_progress"):
        status_board.append({"phase": phase, "event": "in_progress"}, **kw)
    status_board.append({"phase": phase, "event": "ready"}, **kw)
    status_board.append({"phase": phase, "event": "in_progress"}, **kw)
    with pytest.raises(status_board.StatusError, match="passes only with --report"):
        status_board.append({"phase": phase, "event": "passed"}, **kw)
    status_board.append({"et": et, "event": "frozen"}, **kw)
    with pytest.raises(status_board.StatusError, match="require --report"):
        status_board.append({"et": et, "event": "passed"}, **kw)
    status_board.append({"et": et, "event": "passed", "report": "reports/x.md"}, **kw)
    with pytest.raises(status_board.StatusError, match="unknown exit test"):
        status_board.append({"et": "ET-NOPE-1", "event": "frozen"}, **kw)
    board = status_board.render(**kw)
    assert "# Status board" in board
    assert f"| {et} |" in board
    assert "WO-001" in board


def test_render_on_real_repo_config(root: Path) -> None:
    board = status_board.render(
        ledger=root / "work_orders" / "STATUS.jsonl",
        phases_path=root / "config" / "phases.json",
        root=root,
    )
    assert "## Phases" in board and "## Work orders" in board


# ----------------------------------------------------------------------------- append-only check


def _git(repo: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
    }
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True, env=env
    ).stdout


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "git-repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "ledgers").mkdir()
    (repo / "reports").mkdir()
    (repo / "data").mkdir()
    (repo / "work_orders").mkdir()
    (repo / "ledgers" / "runs.jsonl").write_text('{"run":1}\n')
    (repo / "reports" / "WO-001-demo.md").write_text("# report\n")
    (repo / "data" / "manifest.json").write_text("{}\n")
    (repo / "work_orders" / "WO-001-demo.md").write_text("# WO-001 | demo\n")
    (repo / "work_orders" / "STATUS.jsonl").write_text(
        '{"wo":"WO-001","event":"accepted","report":"reports/WO-001-demo.md","commit":"x"}\n'
    )
    (repo / "free.txt").write_text("free\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "switch", "-q", "-c", "wo/WO-002")
    return repo


def test_append_only_allows_pure_appends(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    with (repo / "ledgers" / "runs.jsonl").open("a") as f:
        f.write('{"run":2}\n')
    with (repo / "reports" / "WO-001-demo.md").open("a") as f:
        f.write("\n## Errata\n- 2026-10-31: note\n")
    (repo / "free.txt").write_text("changed freely\n")
    _git(repo, "commit", "-qam", "append")
    assert check_immutable.evaluate("main", cwd=repo) == []


def test_append_only_rejects_edits_deletes_and_frozen_wo(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    (repo / "ledgers" / "runs.jsonl").write_text('{"run":1,"edited":true}\n')  # rewrite, not append
    (repo / "data" / "manifest.json").write_text('{"changed":1}\n')  # write-once path modified
    (repo / "reports" / "WO-001-demo.md").unlink()  # deletion
    (repo / "work_orders" / "WO-001-demo.md").write_text("# WO-001 | demo edited\n")  # frozen WO
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "violations")
    violations = check_immutable.evaluate("main", cwd=repo)
    joined = "\n".join(violations)
    assert "ledgers/runs.jsonl: modified in a way that is not a pure append" in joined
    assert "data/manifest.json: modified (write-once" in joined
    assert "reports/WO-001-demo.md: deleted" in joined
    assert "WO-001 is accepted (frozen" in joined
    assert len(violations) == 4


def test_append_only_rejects_rename_of_protected_path(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    _git(repo, "mv", "reports/WO-001-demo.md", "reports/WO-001-renamed.md")
    _git(repo, "commit", "-qm", "rename")
    violations = check_immutable.evaluate("main", cwd=repo)
    assert any("renamed" in v for v in violations)


# ----------------------------------------------------------------------------- secrets and paths


def test_secret_scan_flags_patterns_and_paths(tmp_path: Path) -> None:
    base = tmp_path / "scan"
    (base / "tools").mkdir(parents=True)
    fake_key = "AKIA" + "ABCDEFGHIJKLMNOP"
    fake_path = "/Users/" + "someone/Desktop/x"
    (base / "notes.md").write_text(f"key {fake_key} here\nsee {fake_path}\n")
    (base / "clean.md").write_text("nothing to see; placeholder /home/user/project is allowed\n")
    hits = scan_secrets.scan(base)
    assert any("AWS access key id" in h for h in hits)
    assert any("macOS home path" in h for h in hits)
    assert not any(h.startswith("clean.md") for h in hits)


def test_repository_has_no_secrets_or_machine_paths(root: Path) -> None:
    assert scan_secrets.scan(root) == []


# ----------------------------------------------------------------------------- links and hashes


def test_markdown_links_resolve(root: Path) -> None:
    assert check_links.check(root) == []


def test_link_checker_detects_broken_link(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text(
        "see [b](b.md) and [web](https://example.com) and [gone](missing.md)\n"
    )
    (tmp_path / "b.md").write_text("ok\n")
    broken = check_links.check(tmp_path)
    assert len(broken) == 1 and "missing.md" in broken[0]


def test_hash_locks_hold(root: Path) -> None:
    assert check_hashes.check_contract() == []
    assert check_hashes.check_program() == []


# ----------------------------------------------------------------------------- budget preflight


def _budget_and_plan(root: Path) -> tuple[dict[str, object], dict[str, object]]:
    budget = json.loads((root / "config" / "budget.json").read_text())
    plan = json.loads((root / "config" / "cpu-smoke-plan.json").read_text())
    return budget, plan


def test_budget_local_arithmetic_only(root: Path) -> None:
    budget, plan = _budget_and_plan(root)
    result = budget_preflight.preflight(budget, plan)
    assert result["expected_seconds"] == pytest.approx(0.05)
    assert result["execution_performed"] is False
    assert result["spend_authorized"] is False


def test_budget_paid_never_enabled_by_config(root: Path) -> None:
    budget, plan = _budget_and_plan(root)
    budget.update(
        approved_run_cap_usd=100, approved_project_cap_usd=100, paid_execution_enabled=True
    )
    plan.update(billing_mode="gpu_rental", gpu_count=1, gpu_hourly_usd=1)
    with pytest.raises(budget_preflight.BudgetError, match="blocked"):
        budget_preflight.preflight(budget, plan)


def test_budget_expected_cost_units(root: Path) -> None:
    _budget, plan = _budget_and_plan(root)
    plan.update(
        gpu_count=2,
        gpu_hourly_usd=3,
        planned_steps=10,
        measured_seconds_per_step=30,
        setup_seconds=60,
        evaluation_seconds=0,
        transfer_shutdown_seconds=0,
        hard_wall_seconds=720,
        storage_egress_tax_usd=0.2,
        cost_margin_fraction=0,
    )
    result = budget_preflight.estimate(plan)
    assert result["expected_cost_usd"] == pytest.approx(0.8)
    assert result["conditional_reserved_cost_usd"] == pytest.approx(1.4)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("planned_steps", -1),
        ("gpu_hourly_usd", float("nan")),
        ("gpu_count", 1.5),
        ("measured_seconds_per_step", 0),
        ("storage_egress_tax_usd", float("inf")),
    ],
)
def test_budget_invalid_numeric(root: Path, key: str, value: float) -> None:
    budget, plan = _budget_and_plan(root)
    plan[key] = value
    with pytest.raises(budget_preflight.BudgetError):
        budget_preflight.preflight(budget, plan)


def test_budget_caps(root: Path) -> None:
    budget, plan = _budget_and_plan(root)
    budget["max_steps"] = 2
    with pytest.raises(budget_preflight.BudgetError, match="step cap"):
        budget_preflight.preflight(budget, plan)
    budget, plan = _budget_and_plan(root)
    budget["max_wall_seconds"] = 2
    with pytest.raises(budget_preflight.BudgetError, match="wall-time"):
        budget_preflight.preflight(budget, plan)
    budget, plan = _budget_and_plan(root)
    del plan["measured_seconds_per_step"]
    with pytest.raises(budget_preflight.BudgetError, match="missing"):
        budget_preflight.preflight(budget, plan)
