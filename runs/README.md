# runs/

One directory per run: `runs/<YYYYMMDDTHHMMSSZ>_<id>/` created by `core.runs.new_run_dir` (exclusive create, never reused). Contents and the start/end ledger lines are described in `docs/DATA_POLICY.md §2`. Run directories are **never deleted or modified** after the run ends; failed and interrupted runs stay.
