#!/usr/bin/env python3
"""Scan repository text files for secrets and machine-specific absolute paths.

Exit 1 on any hit. This is a cheap regex guard, not a replacement for keeping credentials out of
the repository in the first place (AGENTS.md section 10).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
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
TEXT_SUFFIXES = {
    ".md",
    ".py",
    ".json",
    ".jsonl",
    ".yml",
    ".yaml",
    ".toml",
    ".txt",
    ".cfg",
    ".ini",
    ".sh",
    ".csv",
}
TEXT_NAMES = {"Makefile", "Dockerfile", ".gitignore", ".editorconfig", ".env.example"}

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("Hugging Face token", re.compile(r"hf_[A-Za-z0-9]{30,}")),
    ("RunPod API key", re.compile(r"rpa_[A-Za-z0-9]{30,}")),
    ("OpenAI-style key", re.compile(r"\bsk-[A-Za-z0-9_-]{32,}\b")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    (
        "generic assignment",
        re.compile(r"(?i)\b(api[_-]?key|secret|password|token)\b\s*[:=]\s*['\"][^'\"\s]{12,}['\"]"),
    ),
)

PATH_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("macOS home path", re.compile(r"/Users/[A-Za-z0-9._-]+/")),
    ("Linux home path", re.compile(r"/home/(?!user/|<)[A-Za-z0-9._-]+/")),
    ("Windows user path", re.compile(r"[A-Za-z]:\\\\Users\\\\")),
    ("assistant scratch path", re.compile(r"/mnt/user-data|/tmp/claude")),
)


def iter_text_files(base: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(base).parts):
            continue
        if path.suffix in TEXT_SUFFIXES or path.suffix == "" or path.name in TEXT_NAMES:
            files.append(path)
    return files


def scan(base: Path) -> list[str]:
    hits: list[str] = []
    for path in iter_text_files(base):
        rel = path.relative_to(base)
        if rel.as_posix() == "tools/scan_secrets.py":
            continue  # the pattern table itself
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            for label, pattern in SECRET_PATTERNS + PATH_PATTERNS:
                if pattern.search(line):
                    hits.append(f"{rel}:{number}: {label}")
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    hits = scan(args.root.resolve())
    for hit in hits:
        print(f"FAIL: {hit}")
    if hits:
        return 1
    print("secrets/absolute-path scan OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
