"""Token-bucket rate limiter with exponential backoff on HTTP 429."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from kestrel.errors import DataError


@dataclass
class TokenBucket:
    """Classic token bucket: ``rate`` tokens per second up to ``capacity``.

    The sleep and clock functions are injectable so tests never wait.
    """

    rate: float
    capacity: float
    sleep: Callable[[float], None] = time.sleep
    monotonic: Callable[[], float] = time.monotonic
    _tokens: float = field(init=False)
    _last: float = field(init=False)
    slept_total: float = field(init=False, default=0.0)

    def __post_init__(self) -> None:
        """Start full."""
        self._tokens = self.capacity
        self._last = self.monotonic()

    def _refill(self) -> None:
        now = self.monotonic()
        self._tokens = min(self.capacity, self._tokens + (now - self._last) * self.rate)
        self._last = now

    def acquire(self, n: float = 1.0) -> None:
        """Block until ``n`` tokens are available, then consume them."""
        self._refill()
        if self._tokens < n:
            wait = (n - self._tokens) / self.rate
            self.slept_total += wait
            self.sleep(wait)
            self._refill()
            self._tokens = max(self._tokens, n)
        self._tokens -= n


def with_backoff(
    fn: Callable[[], object],
    *,
    is_rate_limited: Callable[[BaseException], bool],
    sleep: Callable[[float], None] = time.sleep,
    max_attempts: int = 5,
    base_delay: float = 1.0,
) -> object:
    """Call ``fn``; on a rate-limit error sleep ``base_delay * 2**attempt`` and retry.

    Args:
        fn: Zero-argument callable.
        is_rate_limited: Predicate deciding whether an exception is a 429-style limit.
        sleep: Injectable sleep.
        max_attempts: Total attempts before giving up.
        base_delay: First delay in seconds.

    Returns:
        Whatever ``fn`` returns.

    Raises:
        DataError: After ``max_attempts`` consecutive rate-limit errors.
    """
    last: BaseException | None = None
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as exc:
            if not is_rate_limited(exc):
                raise
            last = exc
            sleep(base_delay * (2**attempt))
    raise DataError(f"rate limited after {max_attempts} attempts: {last}")
