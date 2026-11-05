"""Notifier protocol, alert type, console and null implementations, and the rate limiter."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal, Protocol

from kestrel.clock import Clock, RealClock
from kestrel.logsetup import get_logger

log = get_logger(__name__)

AlertType = Literal[
    "halt", "reconcile_drift", "adapter_error_streak", "stale_data", "daily_report", "weekly_report", "budget_80pct", "info"
]
Severity = Literal["info", "warning", "critical"]

DEFAULT_SEVERITY: dict[str, Severity] = {
    "halt": "critical",
    "reconcile_drift": "warning",
    "adapter_error_streak": "warning",
    "stale_data": "warning",
    "daily_report": "info",
    "weekly_report": "info",
    "budget_80pct": "info",
    "info": "info",
}


@dataclass(frozen=True)
class Alert:
    """One message for the owner's phone or console."""

    type: AlertType
    title: str
    body: str
    severity: Severity | None = None
    attachment: Path | None = None
    meta: dict[str, str] = field(default_factory=dict)

    @property
    def level(self) -> Severity:
        """Explicit severity or the default for the type."""
        return self.severity or DEFAULT_SEVERITY.get(self.type, "info")


class Notifier(Protocol):
    """Deliver an alert somewhere."""

    name: str

    def send(self, alert: Alert) -> bool:
        """Deliver ``alert``; return True if it was sent."""
        ...


class NullNotifier:
    """Swallows everything. Used when no Telegram token is present."""

    name = "null"

    def __init__(self) -> None:
        """Keep a count for tests."""
        self.dropped = 0

    def send(self, alert: Alert) -> bool:
        """Drop the alert."""
        self.dropped += 1
        return False


class ConsoleNotifier:
    """Logs alerts through structlog at the matching level."""

    name = "console"

    def send(self, alert: Alert) -> bool:
        """Log the alert."""
        payload = {"alert_type": alert.type, "title": alert.title, "body": alert.body, **alert.meta}
        if alert.level == "critical":
            log.critical("alert", **payload)
        elif alert.level == "warning":
            log.warning("alert", **payload)
        else:
            log.info("alert", **payload)
        return True


class RateLimitedNotifier:
    """No more than one alert of the same type per window, except ``halt``."""

    def __init__(self, inner: Notifier, *, window: timedelta = timedelta(minutes=15), clock: Clock | None = None) -> None:
        """Wrap ``inner``."""
        self.inner = inner
        self.name = f"ratelimited({inner.name})"
        self.window = window
        self.clock = clock or RealClock()
        self._last: dict[str, datetime] = {}
        self.suppressed = 0

    def send(self, alert: Alert) -> bool:
        """Forward unless the same type was sent inside the window."""
        now = self.clock.now()
        if alert.type != "halt":
            last = self._last.get(alert.type)
            if last is not None and now - last < self.window:
                self.suppressed += 1
                return False
        self._last[alert.type] = now
        return self.inner.send(alert)
