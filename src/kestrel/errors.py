"""Exception hierarchy for kestrel.

Every error raised by kestrel code derives from :class:`KestrelError` so callers can catch
one base. The CLI maps each subclass to an exit code (see :mod:`kestrel.cli`).
"""

from __future__ import annotations


class KestrelError(Exception):
    """Base class for all kestrel errors."""

    exit_code: int = 1


class ConfigError(KestrelError):
    """Invalid configuration, invalid strategy parameters, or a forbidden endpoint."""

    exit_code = 1


class DataError(KestrelError):
    """Missing, malformed, or gappy market data."""

    exit_code = 2


class AdapterError(KestrelError):
    """A broker or exchange adapter failed, refused, or is unreachable."""

    exit_code = 3


class RiskBreach(KestrelError):
    """A hard risk limit was breached and the book was halted."""

    exit_code = 4


class NaiveDatetimeWarning(UserWarning):
    """Raised as an error in tests when a naive datetime reaches a boundary that requires UTC."""
