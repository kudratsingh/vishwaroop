"""Strict configuration loading.

Configuration comes from versioned JSON files, never from environment surprises. Files are parsed
with the strict parser (no duplicate keys, no NaN) and optionally validated against a JSON Schema.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .jsonutil import StrictJSONError, parse_strict


class ConfigError(ValueError):
    """Raised when a configuration file is missing, malformed, or fails its schema."""


def load_json(path: Path) -> Any:
    """Load and strictly parse a JSON file."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    try:
        return parse_strict(text)
    except StrictJSONError as exc:
        raise ConfigError(f"{path}: {exc}") from exc


def load_validated(path: Path, schema_path: Path) -> dict[str, Any]:
    """Load a JSON object and validate it against a Draft 2020-12 schema file."""
    from jsonschema import (
        Draft202012Validator,
        FormatChecker,
    )  # imported lazily: tooling dependency

    value = load_json(path)
    schema = load_json(schema_path)
    if not isinstance(value, dict):
        raise ConfigError(f"{path}: top-level value must be an object")
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
        key=lambda e: list(map(str, e.path)),
    )
    if errors:
        first = errors[0]
        raise ConfigError(f"{path}: {'/'.join(map(str, first.path)) or '<root>'}: {first.message}")
    return value


def require_keys(value: dict[str, Any], keys: tuple[str, ...], *, where: str) -> None:
    """Fail loudly when a configuration object lacks required keys."""
    missing = [k for k in keys if k not in value]
    if missing:
        raise ConfigError(f"{where}: missing keys {missing}")
