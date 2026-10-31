#!/usr/bin/env python3
"""Verify the vendored contract release and the program document against their locks.

Checks (all must pass; exit code 1 otherwise):
  1. every file listed in contracts/v1/SHA256SUMS.json has the recorded sha256;
  2. no file in contracts/v1 (other than SHA256SUMS.json itself) is missing from the manifest;
  3. sha256(contracts/v1/SHA256SUMS.json) equals config/contract-lock.json["manifest_sha256"];
  4. sha256(PROGRAM.md) equals config/program-lock.json["program_sha256"].

With ``--write-kit-manifest`` the tool additionally (re)writes the repository-level SHA256SUMS.json
covering every tracked-style file (used at packaging time only; CI never writes).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts" / "v1"
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
}


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_files(base: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(base.rglob("*")):
        if path.is_file() and not any(part in SKIP_DIRS for part in path.relative_to(base).parts):
            files.append(path)
    return files


def check_contract() -> list[str]:
    problems: list[str] = []
    manifest_path = CONTRACT / "SHA256SUMS.json"
    if not manifest_path.is_file():
        return [f"missing {manifest_path.relative_to(ROOT)}"]
    manifest: dict[str, str] = json.loads(manifest_path.read_text(encoding="utf-8"))
    listed = set(manifest)
    present = {str(p.relative_to(CONTRACT)) for p in iter_files(CONTRACT)} - {"SHA256SUMS.json"}
    for rel in sorted(listed - present):
        problems.append(f"contract manifest lists missing file: {rel}")
    for rel in sorted(present - listed):
        problems.append(f"contract file not in manifest: {rel}")
    for rel in sorted(listed & present):
        actual = sha256_of(CONTRACT / rel)
        if actual != manifest[rel]:
            problems.append(f"contract hash mismatch: {rel}")
    lock_path = ROOT / "config" / "contract-lock.json"
    if not lock_path.is_file():
        problems.append("missing config/contract-lock.json")
    else:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        if lock.get("manifest_sha256") != sha256_of(manifest_path):
            problems.append(
                "config/contract-lock.json manifest_sha256 != sha256(contracts/v1/SHA256SUMS.json)"
            )
    return problems


def check_program() -> list[str]:
    program = ROOT / "PROGRAM.md"
    lock_path = ROOT / "config" / "program-lock.json"
    if not program.is_file():
        return ["missing PROGRAM.md"]
    if not lock_path.is_file():
        return ["missing config/program-lock.json"]
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if lock.get("program_sha256") != sha256_of(program):
        return [
            "config/program-lock.json program_sha256 != sha256(PROGRAM.md); "
            "update both repositories together"
        ]
    return []


def write_kit_manifest() -> Path:
    target = ROOT / "SHA256SUMS.json"
    entries = {str(p.relative_to(ROOT)): sha256_of(p) for p in iter_files(ROOT) if p != target}
    target.write_text(json.dumps(entries, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def verify_kit_manifest() -> list[str]:
    target = ROOT / "SHA256SUMS.json"
    if not target.is_file():
        return ["missing repository SHA256SUMS.json"]
    recorded: dict[str, str] = json.loads(target.read_text(encoding="utf-8"))
    problems: list[str] = []
    present = {str(p.relative_to(ROOT)) for p in iter_files(ROOT)} - {"SHA256SUMS.json"}
    for rel in sorted(set(recorded) - present):
        problems.append(f"kit manifest lists missing file: {rel}")
    for rel in sorted(present - set(recorded)):
        problems.append(f"file not in kit manifest: {rel}")
    for rel in sorted(set(recorded) & present):
        if sha256_of(ROOT / rel) != recorded[rel]:
            problems.append(f"kit hash mismatch: {rel}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write-kit-manifest", action="store_true", help="packaging only: rewrite SHA256SUMS.json"
    )
    parser.add_argument(
        "--verify-kit-manifest",
        action="store_true",
        help="also verify the repository SHA256SUMS.json",
    )
    args = parser.parse_args(argv)
    if args.write_kit_manifest:
        print(f"wrote {write_kit_manifest().relative_to(ROOT)}")
        return 0
    problems = check_contract() + check_program()
    if args.verify_kit_manifest:
        problems += verify_kit_manifest()
    for problem in problems:
        print(f"FAIL: {problem}")
    if problems:
        return 1
    print(
        "hash locks OK: contract release, program document"
        + (", kit manifest" if args.verify_kit_manifest else "")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
