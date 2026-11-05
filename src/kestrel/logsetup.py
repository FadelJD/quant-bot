"""structlog configuration: JSON lines on disk, pretty console in the foreground, secrets redacted."""

from __future__ import annotations

import logging
import logging.handlers
import re
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

import structlog

_REDACT_RE = re.compile(r"(?i)\b(\w*(?:key|secret|token|password)\w*)\s*[=:]\s*\S+")
_REDACT_KEYS = re.compile(r"(?i)(key|secret|token|password)")


def redact(value: str) -> str:
    """Replace anything that looks like ``key=value`` with ``key=***``.

    Args:
        value: Arbitrary text.

    Returns:
        The text with secret-looking assignments masked.
    """
    return _REDACT_RE.sub(lambda m: f"{m.group(1)}=***", value)


def redact_processor(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """structlog processor that masks secret-looking keys and values in every event."""
    for key in list(event_dict):
        val = event_dict[key]
        if _REDACT_KEYS.search(key):
            event_dict[key] = "***"
        elif isinstance(val, str):
            event_dict[key] = redact(val)
    return event_dict


def configure_logging(
    log_dir: Path | None = None,
    level: str = "INFO",
    console: bool = True,
    retention_days: int = 30,
) -> None:
    """Configure structlog and the stdlib root logger.

    Args:
        log_dir: Directory for ``kestrel-YYYY-MM-DD.jsonl`` files. ``None`` disables file logs.
        level: Minimum level name (``DEBUG``, ``INFO``, ...).
        console: Whether to emit a human-readable console stream.
        retention_days: How many daily files to keep.
    """
    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        redact_processor,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.setLevel(level.upper())

    if console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                processor=structlog.dev.ConsoleRenderer(colors=False), foreign_pre_chain=shared
            )
        )
        root.addHandler(console_handler)

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.TimedRotatingFileHandler(
            log_dir / "kestrel.jsonl",
            when="midnight",
            utc=True,
            backupCount=retention_days,
            encoding="utf-8",
        )
        file_handler.suffix = "%Y-%m-%d"
        file_handler.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                processor=structlog.processors.JSONRenderer(), foreign_pre_chain=shared
            )
        )
        root.addHandler(file_handler)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger for ``name``."""
    return structlog.get_logger(name)  # type: ignore[no-any-return]
