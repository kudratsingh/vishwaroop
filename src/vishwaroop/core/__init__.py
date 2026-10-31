"""Shared, dependency-free building blocks that enforce the repository's record rules.

Every module here exists to make the append-only, never-overwrite policy (AGENTS.md section 6)
the default behaviour of the code rather than a matter of discipline:

- ``ledger``    append-only JSON Lines ledgers (no truncation path exists)
- ``artifacts`` content-addressed artifact store (no delete; refuses to replace differing bytes)
- ``runs``      exclusive-create run directories with the required provenance files
- ``log``       structured JSON logging to append-only files
- ``config``    strict JSON loading with duplicate-key and non-finite rejection
- ``jsonutil``  the shared strict JSON parser

This package is copied byte-identically into both project repositories under their own package
namespace; it is a vendored library, not a shared runtime.
"""

from __future__ import annotations

__all__ = ["artifacts", "config", "jsonutil", "ledger", "log", "runs"]
