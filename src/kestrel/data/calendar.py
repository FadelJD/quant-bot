"""Market calendars: crypto is 24/7, US equities follow the NYSE schedule.

``pandas_market_calendars`` is imported lazily so the crypto path has no dependency on it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Protocol

import pandas as pd

from kestrel.clock import ensure_utc
from kestrel.config import TIMEFRAME_SECONDS


class MarketCalendar(Protocol):
    """Session and bar-boundary queries for one market."""

    def is_open(self, ts: datetime) -> bool:
        """Whether the market is in a regular session at ``ts``."""
        ...

    def next_open(self, ts: datetime) -> datetime:
        """The first session open strictly after ``ts``."""
        ...

    def next_bar_close(self, ts: datetime, timeframe: str) -> datetime:
        """The next bar boundary strictly after ``ts`` on which the market is open."""
        ...

    def sessions(self, start: datetime, end: datetime) -> pd.DatetimeIndex:
        """Session dates (UTC midnight for crypto, session open for equities) in ``[start, end]``."""
        ...


class CryptoCalendar:
    """Always open; bars align to UTC boundaries."""

    def is_open(self, ts: datetime) -> bool:
        """Crypto never closes."""
        ensure_utc(ts)
        return True

    def next_open(self, ts: datetime) -> datetime:
        """Return the next bar boundary (the market is already open)."""
        return self.next_bar_close(ts, "1d")

    def next_bar_close(self, ts: datetime, timeframe: str) -> datetime:
        """Return the next UTC-aligned boundary strictly after ``ts`` for the timeframe."""
        t = ensure_utc(ts)
        step = TIMEFRAME_SECONDS[timeframe]
        epoch = int(t.timestamp())
        nxt = (epoch // step + 1) * step
        return datetime.fromtimestamp(nxt, tz=UTC)

    def sessions(self, start: datetime, end: datetime) -> pd.DatetimeIndex:
        """Every UTC day between ``start`` and ``end`` inclusive."""
        s = ensure_utc(start).replace(hour=0, minute=0, second=0, microsecond=0)
        return pd.date_range(s, ensure_utc(end), freq="1D", tz="UTC", name="ts")


class NyseCalendar:
    """NYSE regular hours, early closes and holidays via ``pandas_market_calendars``."""

    def __init__(self) -> None:
        """Load the XNYS calendar lazily."""
        import pandas_market_calendars as pmc

        self._cal = pmc.get_calendar("XNYS")

    @lru_cache(maxsize=16)
    def _schedule(self, year: int) -> pd.DataFrame:
        return self._cal.schedule(start_date=f"{year}-01-01", end_date=f"{year}-12-31")

    def _row_for(self, ts: datetime) -> pd.Series | None:
        t = ensure_utc(ts)
        sched = self._schedule(t.year)
        day = pd.Timestamp(t).tz_convert("America/New_York").normalize().tz_localize(None)
        if day in sched.index:
            return sched.loc[day]
        return None

    def is_open(self, ts: datetime) -> bool:
        """Whether ``ts`` falls inside a regular session (open inclusive, close exclusive)."""
        row = self._row_for(ts)
        if row is None:
            return False
        t = pd.Timestamp(ensure_utc(ts))
        return bool(row["market_open"] <= t < row["market_close"])

    def next_open(self, ts: datetime) -> datetime:
        """First session open strictly after ``ts``."""
        t = pd.Timestamp(ensure_utc(ts))
        for year in (t.year, t.year + 1):
            sched = self._schedule(year)
            opens = sched["market_open"]
            later = opens[opens > t]
            if len(later):
                return later.iloc[0].to_pydatetime()
        raise ValueError("no session found within a year")  # pragma: no cover

    def next_bar_close(self, ts: datetime, timeframe: str) -> datetime:
        """Next bar boundary inside a session, or the next session's first boundary.

        Daily bars close at the session close; intraday bars at UTC-aligned boundaries that fall
        within the session.
        """
        t = ensure_utc(ts)
        if timeframe == "1d":
            row = self._row_for(t)
            if row is not None and pd.Timestamp(t) < row["market_close"]:
                return row["market_close"].to_pydatetime()
            nxt_open = self.next_open(t)
            row = self._row_for(nxt_open)
            assert row is not None
            return row["market_close"].to_pydatetime()
        step = TIMEFRAME_SECONDS[timeframe]
        candidate = datetime.fromtimestamp((int(t.timestamp()) // step + 1) * step, tz=UTC)
        for _ in range(10_000):
            if self.is_open(candidate - timedelta(seconds=1)):
                return candidate
            candidate = self.next_open(candidate)
            candidate = datetime.fromtimestamp((int(candidate.timestamp()) // step + 1) * step, tz=UTC)
        raise ValueError("no bar boundary found")  # pragma: no cover

    def sessions(self, start: datetime, end: datetime) -> pd.DatetimeIndex:
        """Session open timestamps in ``[start, end]``."""
        s, e = ensure_utc(start), ensure_utc(end)
        sched = self._cal.schedule(start_date=s.date(), end_date=e.date())
        return pd.DatetimeIndex(sched["market_open"], name="ts").tz_convert("UTC")


def calendar_for(market: str) -> MarketCalendar:
    """Return the calendar for a market name."""
    if market == "crypto":
        return CryptoCalendar()
    if market == "equities":
        return NyseCalendar()
    raise ValueError(f"unknown market {market!r}")
