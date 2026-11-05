"""Deterministic synthetic OHLCV for tests, fixtures, and the validation layer's resampling test."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

from kestrel.clock import ensure_utc
from kestrel.config import TIMEFRAME_SECONDS
from kestrel.data.schema import attach_meta


def make_synthetic_ohlcv(
    seed: int,
    drift: float,
    vol: float,
    n: int,
    *,
    start: datetime | None = None,
    timeframe: str = "1d",
    symbol: str = "SYN/USDT",
    market: str = "crypto",
    start_price: float = 100.0,
    regime_length: int | None = None,
    volume: float = 1_000_000.0,
) -> pd.DataFrame:
    """Generate a geometric random walk with optional alternating drift regimes.

    Args:
        seed: RNG seed; the same seed always yields the same frame.
        drift: Annualised drift of log returns.
        vol: Annualised volatility of log returns.
        n: Number of bars.
        start: UTC start timestamp (default 2022-01-01).
        timeframe: Bar size.
        symbol: Symbol label.
        market: ``crypto`` or ``equities``.
        start_price: First close.
        regime_length: If set, drift flips sign every ``regime_length`` bars, giving a trend
            strategy something real to catch.
        volume: Mean bar volume in base units.

    Returns:
        A canonical OHLCV frame.
    """
    rng = np.random.default_rng(seed)
    per_year = 365.0 * 86_400 / TIMEFRAME_SECONDS[timeframe]
    mu = drift / per_year
    sigma = vol / np.sqrt(per_year)
    sign = np.ones(n)
    if regime_length:
        sign = np.where((np.arange(n) // regime_length) % 2 == 0, 1.0, -1.0)
    rets = mu * sign + sigma * rng.standard_normal(n)
    close = start_price * np.exp(np.cumsum(rets))
    open_ = np.empty(n)
    open_[0] = start_price
    open_[1:] = close[:-1] * np.exp(sigma * 0.1 * rng.standard_normal(n - 1))
    wick = np.abs(sigma * rng.standard_normal(n)) * close
    high = np.maximum(open_, close) + wick
    low = np.minimum(open_, close) - wick
    low = np.maximum(low, 1e-6)
    vol_series = volume * np.exp(0.3 * rng.standard_normal(n))
    begin = ensure_utc(start) if start else datetime.fromisoformat("2022-01-01T00:00:00+00:00")
    index = pd.date_range(begin, periods=n, freq=pd.Timedelta(seconds=TIMEFRAME_SECONDS[timeframe]), tz="UTC", name="ts")
    frame = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": vol_series}, index=index
    )
    return attach_meta(frame, symbol, market, timeframe)


def resample_path(frame: pd.DataFrame, seed: int, block: int = 20) -> pd.DataFrame:
    """Block-bootstrap a price path: keeps the return distribution, scrambles the calendar.

    Used by the memorisation check: a strategy that keyed off specific dates loses its edge here,
    a strategy that keyed off price structure keeps most of it.

    Args:
        frame: Canonical OHLCV frame.
        seed: RNG seed.
        block: Block length in bars.

    Returns:
        A frame with the same index and the same shape statistics but a resampled path.
    """
    rng = np.random.default_rng(seed)
    n = len(frame)
    if n < 2:
        return frame.copy()
    close = frame["close"].to_numpy()
    log_ret = np.diff(np.log(close))
    ratios = {
        col: (frame[col].to_numpy() / close) for col in ("open", "high", "low")
    }
    volume = frame["volume"].to_numpy()
    n_blocks = int(np.ceil((n - 1) / block))
    starts = rng.integers(0, max(1, len(log_ret) - block + 1), size=n_blocks)
    idx = np.concatenate([np.arange(s, s + block) for s in starts])[: n - 1]
    idx = np.clip(idx, 0, len(log_ret) - 1)
    new_close = close[0] * np.exp(np.concatenate([[0.0], np.cumsum(log_ret[idx])]))
    bar_idx = np.concatenate([[0], idx + 1])
    out = frame.copy()
    out["close"] = new_close
    for col, ratio in ratios.items():
        out[col] = new_close * ratio[bar_idx]
    out["volume"] = volume[bar_idx]
    out["high"] = np.maximum(out["high"], np.maximum(out["open"], out["close"]))
    out["low"] = np.minimum(out["low"], np.minimum(out["open"], out["close"]))
    return out
