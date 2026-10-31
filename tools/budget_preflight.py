#!/usr/bin/env python3
"""Estimate a proposed run and check it against local limits. NEVER executes or authorizes jobs.

This is a cost estimator and refusal check (docs/BUDGET_AND_LAUNCHER.md). It does not reserve funds,
launch anything, or stop a rental. Paid plans are refused until the enforcing launcher exists and
its provider-teardown tests pass; an agent cannot change that by editing config/budget.json.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

REQUIRED_PLAN_KEYS = (
    "gpu_count",
    "gpu_hourly_usd",
    "planned_steps",
    "measured_seconds_per_step",
    "setup_seconds",
    "evaluation_seconds",
    "transfer_shutdown_seconds",
    "hard_wall_seconds",
    "storage_egress_tax_usd",
    "cost_margin_fraction",
)
REQUIRED_BUDGET_KEYS = (
    "approved_run_cap_usd",
    "approved_project_cap_usd",
    "max_wall_seconds",
    "max_steps",
)


class BudgetError(ValueError):
    """A plan or budget is malformed or exceeds a limit."""


def _number(value: Any, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise BudgetError(f"{name} must be a finite nonnegative number")
    return float(value)


def estimate(plan: dict[str, Any]) -> dict[str, float]:
    """Expected and conditionally-reserved cost from a measured pilot. Pure arithmetic."""
    for key in REQUIRED_PLAN_KEYS:
        if key not in plan:
            raise BudgetError(f"missing {key}")
        _number(plan[key], key)
    for key in ("gpu_count", "planned_steps"):
        if plan[key] != int(plan[key]):
            raise BudgetError(f"{key} must be an integer")
    if plan["planned_steps"] <= 0 or plan["measured_seconds_per_step"] <= 0:
        raise BudgetError("positive steps and measured seconds/step are required")
    runtime = (
        plan["planned_steps"] * plan["measured_seconds_per_step"]
        + plan["setup_seconds"]
        + plan["evaluation_seconds"]
        + plan["transfer_shutdown_seconds"]
    )
    hard_wall = plan["hard_wall_seconds"]
    if hard_wall <= 0 or runtime > hard_wall:
        raise BudgetError("planned duration exceeds hard wall limit")
    rate = plan["gpu_count"] * plan["gpu_hourly_usd"]
    margin = 1 + plan["cost_margin_fraction"]
    # The reserved bound is conditional on actual billable-resource teardown, not trainer exit.
    return {
        "expected_seconds": runtime,
        "expected_cost_usd": (rate * runtime / 3600 + plan["storage_egress_tax_usd"]) * margin,
        "conditional_reserved_cost_usd": (rate * hard_wall / 3600 + plan["storage_egress_tax_usd"])
        * margin,
    }


def preflight(budget: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    """Check a plan against the budget; refuse anything paid or GPU-bearing (no launcher yet)."""
    result = estimate(plan)
    for key in REQUIRED_BUDGET_KEYS:
        if key not in budget:
            raise BudgetError(f"missing budget key {key}")
        _number(budget[key], key)
    if plan["planned_steps"] > budget["max_steps"]:
        raise BudgetError("step cap exceeded")
    if plan["hard_wall_seconds"] > budget["max_wall_seconds"]:
        raise BudgetError("wall-time cap exceeded")
    if result["conditional_reserved_cost_usd"] > budget["approved_run_cap_usd"]:
        raise BudgetError("run cost cap exceeded")
    if result["conditional_reserved_cost_usd"] > budget["approved_project_cap_usd"]:
        raise BudgetError("project cost cap exceeded")
    paid_or_gpu = (
        plan.get("billing_mode") != "local_unmetered"
        or plan["gpu_count"] != 0
        or result["conditional_reserved_cost_usd"] != 0
    )
    if paid_or_gpu:
        raise BudgetError(
            "paid/resource launches blocked: enforcing launcher/provider lifecycle not implemented"
        )
    return {
        **result,
        "status": "local_plan_within_configured_limits",
        "execution_performed": False,
        "spend_authorized": False,
        "warning": (
            "Preflight only. No time/step supervision, ledger reservation, or cloud teardown "
            "was performed."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        budget = json.loads(args.budget.read_text(encoding="utf-8"))
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        print(json.dumps(preflight(budget, plan), indent=2))
        return 0
    except (BudgetError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"REFUSED: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
