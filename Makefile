PYTHON ?= python3
BASE ?= origin/main

.PHONY: check lint format type test hashes secrets links immutable board sim-check help

help:
	@echo "make check      - full CPU tier (lint, type, test, hashes, secrets, links)"
	@echo "make lint       - ruff format --check + ruff check"
	@echo "make format     - ruff format (writes)"
	@echo "make type       - mypy on src/ and tools/"
	@echo "make test       - pytest CPU tier"
	@echo "make hashes     - verify contract + program locks"
	@echo "make secrets    - secret and absolute-path scan"
	@echo "make links      - markdown relative-link check"
	@echo "make immutable  - append-only check vs BASE (default origin/main)"
	@echo "make board      - regenerate docs/STATUS_BOARD.md from the status ledger"
	@echo "make sim-check  - placeholder: simulator tier is run manually (see docs/WORKFLOW.md section 6)"

check: lint type test hashes secrets links
	@echo "CPU tier: all checks passed"

lint:
	$(PYTHON) -m ruff format --check src tools tests contracts/v1
	$(PYTHON) -m ruff check src tools tests contracts/v1

format:
	$(PYTHON) -m ruff format src tools tests contracts/v1

type:
	$(PYTHON) -m mypy src tools contracts/v1/validate.py contracts/v1/audit_splits.py contracts/v1/writer.py

test:
	$(PYTHON) -m pytest -q

hashes:
	$(PYTHON) tools/check_hashes.py

secrets:
	$(PYTHON) tools/scan_secrets.py

links:
	$(PYTHON) tools/check_links.py

immutable:
	$(PYTHON) tools/check_immutable.py --base $(BASE)

board:
	$(PYTHON) tools/status_board.py --render > docs/STATUS_BOARD.md

sim-check:
	@echo "Simulator tier is not automated in this starter. Run it on a machine with the pinned stack and attach the report (docs/WORKFLOW.md section 6)."
	@echo "Status: not run"
