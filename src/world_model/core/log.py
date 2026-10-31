"""Structured logging: one JSON object per line, UTC timestamps, append-only files.

Use ``get_logger(name, path)`` to log to ``events.jsonl`` inside a run directory. Secrets must never
be passed as fields; ``redact`` masks obvious token-shaped values as a last line of defence.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .jsonutil import dumps_canonical

_SECRET_SHAPES = (
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


def redact(value: Any) -> Any:
    """Mask token-shaped strings anywhere inside a JSON-like value."""
    if isinstance(value, str):
        for shape in _SECRET_SHAPES:
            value = shape.sub("[REDACTED]", value)
        return value
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


class JsonLineFormatter(logging.Formatter):
    """Format a record as a single canonical JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            payload["fields"] = redact(extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return dumps_canonical(payload)


class StructuredAdapter(logging.LoggerAdapter[logging.Logger]):
    """``log.info("msg", fields={...})`` puts the fields in the JSON line."""

    def process(self, msg: str, kwargs: Any) -> tuple[str, Any]:
        fields = kwargs.pop("fields", None)
        extra = dict(kwargs.get("extra") or {})
        if fields is not None:
            extra["fields"] = fields
        kwargs["extra"] = extra
        return msg, kwargs


def get_logger(name: str, path: Path | None = None, level: int = logging.INFO) -> StructuredAdapter:
    """Return a structured logger writing JSON lines to ``path`` (append mode) and to stderr."""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False
    if not logger.handlers:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(JsonLineFormatter())
        logger.addHandler(stream_handler)
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(path, mode="a", encoding="utf-8")
            file_handler.setFormatter(JsonLineFormatter())
            logger.addHandler(file_handler)
    return StructuredAdapter(logger, {})
