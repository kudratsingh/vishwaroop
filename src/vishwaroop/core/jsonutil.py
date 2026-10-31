"""Strict JSON parsing: rejects duplicate keys, NaN/Infinity, and non-finite floats."""

from __future__ import annotations

import json
import math
from typing import Any


class StrictJSONError(ValueError):
    """Raised when text is not acceptable JSON under this repository's rules."""


def _reject_constant(value: str) -> None:
    raise StrictJSONError(f"invalid JSON constant {value!r}")


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StrictJSONError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _assert_finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise StrictJSONError("non-finite numeric value")
    if isinstance(value, dict):
        for item in value.values():
            _assert_finite(item)
    elif isinstance(value, list):
        for item in value:
            _assert_finite(item)


def parse_strict(text: str) -> Any:
    """Parse JSON text, refusing duplicate keys and non-finite numbers."""
    try:
        value = json.loads(
            text, parse_constant=_reject_constant, object_pairs_hook=_no_duplicate_keys
        )
    except json.JSONDecodeError as exc:
        raise StrictJSONError(str(exc)) from exc
    _assert_finite(value)
    return value


def dumps_canonical(value: Any) -> str:
    """Serialize deterministically (sorted keys, compact, no NaN) for hashing and ledgers."""
    _assert_finite(value)
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
