#!/usr/bin/env python3
"""Check that relative Markdown links point at files that exist. Exit 1 on a broken link."""

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
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)")


def iter_markdown(base: Path) -> list[Path]:
    return [
        p
        for p in sorted(base.rglob("*.md"))
        if p.is_file() and not any(part in SKIP_DIRS for part in p.relative_to(base).parts)
    ]


def check(base: Path) -> list[str]:
    broken: list[str] = []
    for md in iter_markdown(base):
        text = md.read_text(encoding="utf-8")
        in_fence = False
        for number, line in enumerate(text.splitlines(), start=1):
            if line.strip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            for raw in LINK.findall(line):
                target = raw.split("#", 1)[0]
                if not target or raw.startswith(("http://", "https://", "mailto:", "urn:")):
                    continue
                candidate = (md.parent / target).resolve()
                if not candidate.exists():
                    broken.append(f"{md.relative_to(base)}:{number}: broken link -> {raw}")
    return broken


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    broken = check(args.root.resolve())
    for item in broken:
        print(f"FAIL: {item}")
    if broken:
        return 1
    print("markdown links OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
