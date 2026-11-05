"""Canonical OHLCV frame and its validation.

One frame shape everywhere: index ``ts`` (UTC, bar open time), columns ``open, high, low, close,
volume, symbol, market, timeframe``. Validation never silently returns a gap.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from kestrel.config import TIMEFRAME_SECONDS
from kestrel.errors import DataError

OHLCV_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close", "volume")
META_COLUMNS: tuple[str, ...] = ("symbol", "market", "timeframe")


@dataclass(frozen=True)
class GapReport:
    """Gaps found in a bar series."""

    n_gaps: int
    largest_bars: int
    locations: list[pd.Timestamp]

    @property
    def has_gaps(self) -> bool:
        """Whether any gap larger than one bar was found."""
        return self.n_gaps > 0


def empty_ohlcv(symbol: str, market: str, timeframe: str) -> pd.DataFrame:
    """Return an empty frame with the canonical columns and a UTC ``ts`` index."""
    frame = pd.DataFrame(
        {col: pd.Series(dtype="float64") for col in OHLCV_COLUMNS}
        | {"symbol": pd.Series(dtype="object"), "market": pd.Series(dtype="object")}
        | {"timeframe": pd.Series(dtype="object")}
    )
    frame.index = pd.DatetimeIndex([], tz="UTC", name="ts")
    frame["symbol"] = frame["symbol"].astype(object)
    _ = (symbol, market, timeframe)
    return frame


def find_gaps(index: pd.DatetimeIndex, timeframe: str, market: str) -> GapReport:
    """Find gaps larger than one bar in a monotonic index.

    For equities, weekend and holiday gaps are expected and skipped by allowing any gap that
    spans at least one weekend day; finer calendar checks live in :mod:`kestrel.data.calendar`.

    Args:
        index: Sorted, unique UTC index of bar open times.
        timeframe: Bar size.
        market: ``crypto`` or ``equities``.

    Returns:
        A :class:`GapReport`.
    """
    if len(index) < 2:
        return GapReport(0, 0, [])
    step = pd.Timedelta(seconds=TIMEFRAME_SECONDS[timeframe])
    diffs = index[1:] - index[:-1]
    bars = (diffs / step).to_numpy()
    if market == "equities":
        # A gap is fine when it crosses a non-trading day; crude but sufficient for daily bars.
        weekend = np.array([(a.dayofweek >= 4) or (b.dayofweek == 0) for a, b in zip(index[:-1], index[1:], strict=True)])
        bad = (bars > 1.0001) & ~weekend & (bars > 4)
    else:
        bad = bars > 1.0001
    locs = [pd.Timestamp(t) for t in index[1:][bad]]
    largest = int(bars[bad].max()) if bad.any() else 0
    return GapReport(int(bad.sum()), largest, locs)


def validate_ohlcv(
    frame: pd.DataFrame,
    *,
    timeframe: str,
    market: str,
    allow_gaps: bool = False,
) -> pd.DataFrame:
    """Validate and normalise an OHLCV frame.

    Checks: required columns, UTC-aware monotonic unique index, no NaN prices, no negative
    prices or volume, ``low <= min(open, close)`` and ``max(open, close) <= high``, and gaps.

    Args:
        frame: Candidate frame.
        timeframe: Expected bar size, used for gap detection.
        market: ``crypto`` or ``equities``.
        allow_gaps: If True, gaps are forward-filled and logged instead of raising.

    Returns:
        A clean copy sorted by time with float64 price columns.

    Raises:
        DataError: On any violation, naming the first offending timestamp where possible.
    """
    missing = [c for c in OHLCV_COLUMNS if c not in frame.columns]
    if missing:
        raise DataError(f"missing OHLCV columns: {missing}")
    out = frame.copy()
    if not isinstance(out.index, pd.DatetimeIndex):
        raise DataError("index must be a DatetimeIndex named ts")
    if out.index.tz is None:
        raise DataError("index must be timezone-aware UTC; naive timestamps are rejected")
    out.index = out.index.tz_convert("UTC")
    out.index.name = "ts"
    if out.index.has_duplicates:
        dup = out.index[out.index.duplicated()][0]
        raise DataError(f"duplicate timestamp at {dup}")
    if not out.index.is_monotonic_increasing:
        out = out.sort_index()
    for col in OHLCV_COLUMNS:
        out[col] = out[col].astype("float64")
    prices = out[["open", "high", "low", "close"]]
    if prices.isna().any().any():
        first = out.index[prices.isna().any(axis=1)][0]
        raise DataError(f"NaN price at {first}")
    if (prices <= 0).any().any():
        first = out.index[(prices <= 0).any(axis=1)][0]
        raise DataError(f"non-positive price at {first}")
    if (out["volume"] < 0).any():
        first = out.index[out["volume"] < 0][0]
        raise DataError(f"negative volume at {first}")
    bad_low = out["low"] > np.minimum(out["open"], out["close"]) + 1e-12
    bad_high = out["high"] < np.maximum(out["open"], out["close"]) - 1e-12
    if bad_low.any() or bad_high.any():
        first = out.index[bad_low | bad_high][0]
        raise DataError(f"OHLC inconsistency (low <= open,close <= high violated) at {first}")
    gaps = find_gaps(out.index, timeframe, market)
    if gaps.has_gaps:
        if not allow_gaps:
            raise DataError(
                f"{gaps.n_gaps} gap(s) larger than one bar; largest {gaps.largest_bars} bars; "
                f"first at {gaps.locations[0]}. Set data.allow_gaps: true to forward-fill."
            )
        out = fill_gaps(out, timeframe)
    return out


def fill_gaps(frame: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Forward-fill missing bars (flat candles at the previous close, zero volume)."""
    step = pd.Timedelta(seconds=TIMEFRAME_SECONDS[timeframe])
    full = pd.date_range(frame.index[0], frame.index[-1], freq=step, tz="UTC", name="ts")
    out = frame.reindex(full)
    filled = out["close"].isna()
    out["close"] = out["close"].ffill()
    for col in ("open", "high", "low"):
        out.loc[filled, col] = out.loc[filled, "close"]
    out["volume"] = out["volume"].fillna(0.0)
    for col in META_COLUMNS:
        if col in out.columns:
            out[col] = out[col].ffill()
    return out


def attach_meta(frame: pd.DataFrame, symbol: str, market: str, timeframe: str) -> pd.DataFrame:
    """Set the ``symbol``, ``market`` and ``timeframe`` columns on a frame (copy)."""
    out = frame.copy()
    out["symbol"] = symbol
    out["market"] = market
    out["timeframe"] = timeframe
    return out
