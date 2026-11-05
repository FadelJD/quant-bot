"""Clock protocol with a real implementation and a simulated one for tests.

All scheduling in kestrel goes through a :class:`Clock` so the live loop can be run against
:class:`SimClock` at any speed. Every timestamp is timezone-aware UTC.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Protocol

from kestrel.errors import ConfigError


def ensure_utc(ts: datetime) -> datetime:
    """Return ``ts`` as a timezone-aware UTC datetime.

    Args:
        ts: A timezone-aware datetime in any zone.

    Returns:
        The same instant expressed in UTC.

    Raises:
        ConfigError: If ``ts`` is naive. Naive datetimes are never accepted at a boundary.
    """
    if ts.tzinfo is None or ts.utcoffset() is None:
        raise ConfigError(f"naive datetime not allowed: {ts!r}; pass a UTC-aware datetime")
    return ts.astimezone(UTC)


class Clock(Protocol):
    """Source of time for schedulers, loggers, and idempotency keys."""

    def now(self) -> datetime:
        """Return the current instant as a timezone-aware UTC datetime."""
        ...

    def sleep_until(self, when: datetime) -> None:
        """Block until ``when`` (UTC). Returns immediately if ``when`` is in the past."""
        ...


class RealClock:
    """Wall clock backed by :func:`datetime.now` and :func:`time.sleep`."""

    def now(self) -> datetime:
        """Return the current UTC time."""
        return datetime.now(tz=UTC)

    def sleep_until(self, when: datetime) -> None:
        """Sleep until ``when``, polling in short slices so a halt can be observed promptly."""
        target = ensure_utc(when)
        while True:
            remaining = (target - self.now()).total_seconds()
            if remaining <= 0:
                return
            time.sleep(min(remaining, 1.0))


class SimClock:
    """Deterministic clock for tests: time only moves when told to.

    ``sleep_until`` advances the clock instantly, which lets a seven-day paper run complete in
    seconds against a mock adapter.
    """

    def __init__(self, start: datetime) -> None:
        """Create a simulated clock.

        Args:
            start: Initial UTC instant.
        """
        self._now = ensure_utc(start)

    def now(self) -> datetime:
        """Return the simulated current time."""
        return self._now

    def sleep_until(self, when: datetime) -> None:
        """Jump the simulated time forward to ``when`` if it is later than now."""
        target = ensure_utc(when)
        if target > self._now:
            self._now = target

    def advance(self, delta: timedelta) -> None:
        """Move the simulated time forward by ``delta``."""
        self._now = self._now + delta

    def set(self, when: datetime) -> None:
        """Set the simulated time to ``when`` (UTC)."""
        self._now = ensure_utc(when)
