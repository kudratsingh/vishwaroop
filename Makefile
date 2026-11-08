PYTHON ?= python3
BASE ?= origin/main

.PHONY: check lint format type test verify secrets links immutable board sim-check torch-test synth-test help

help:
	@echo "make check      - full CPU tier (lint, type, test, verify, secrets, links)"
	@echo "make lint       - ruff format --check + ruff check"
	@echo "make format     - ruff format (writes)"
	@echo "make type       - mypy on src/"
	@echo "make test       - pytest CPU tier, with ironclad's shared tests through its plugin"
	@echo "make verify     - policy copies, pin, install source and contract manifest (ironclad)"
	@echo "make secrets    - secret and absolute-path scan"
	@echo "make links      - markdown relative-link check"
	@echo "make immutable  - append-only check vs BASE (default origin/main)"
	@echo "make board      - regenerate docs/STATUS_BOARD.md from the status ledger"
	@echo "make sim-check  - placeholder: simulator tier is run manually (see docs/WORKFLOW.md section 6)"
	@echo "make torch-test - the torch tests the CPU tier skips, in the robotics env (WO-024)"

check: lint type test verify secrets links
	@echo "CPU tier: all checks passed"

lint:
	$(PYTHON) -m ruff format --check src tests
	$(PYTHON) -m ruff check src tests

format:
	$(PYTHON) -m ruff format src tests

type:
	$(PYTHON) -m mypy src

test:
	$(PYTHON) -m pytest -q

verify:
	ironclad sync-policy --root . --check
	ironclad verify --root .

secrets:
	ironclad-scan-secrets

links:
	ironclad-check-links

immutable:
	ironclad-check-immutable --base $(BASE)

board:
	ironclad-status --render > docs/STATUS_BOARD.md

sim-check:
	@echo "Simulator tier is not automated in this starter. Run it on a machine with the pinned stack and attach the report (docs/WORKFLOW.md section 6)."
	@echo "Status: not run"

# The tests that need torch (skipped on the CPU tier), run in the robotics env, which has it (WO-024).
torch-test:
	PYTHONPATH=src:tests $(HOME)/.cache/vishwaroop-robotics/sim-venv/bin/python -m pytest -q -rs $$(grep -l 'importorskip("torch")' tests/test_*.py)

# The synth tests that need numpy and scipy, which the CPU tier lacks; run in the robotics env.
synth-test:
	PYTHONPATH=src:tests $(HOME)/.cache/vishwaroop-robotics/sim-venv/bin/python -m pytest -q tests/test_synth_*.py
