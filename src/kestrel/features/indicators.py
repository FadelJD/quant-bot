"""Indicator implementations. Every function is causal: row ``t`` uses rows ``<= t`` only.

Column naming matches the feature name, e.g. ``sma_20`` adds a column ``sma_20``. Families with
several outputs add suffixed columns (``macd_12_26_9`` adds ``macd_12_26_9``,
``macd_12_26_9_signal``, ``macd_12_26_9_hist``).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from kestrel.features.registry import _fmt, register


def _name(family: str, params: tuple[float, ...]) -> str:
    return family if not params else family + "_" + "_".join(_fmt(p) for p in params)


# --------------------------------------------------------------------------- returns


@register("ret", n_params=1, lookback=lambda p: int(p[0]), description="Simple return over n bars")
def ret(df: pd.DataFrame, p: tuple[float, ...]) -> pd.DataFrame:
    """Simple return ``close_t / close_{t-n} - 1``."""
    n = int(p[0])
    df[_name("ret", p)] = df["close"] / df["close"].shift(n) - 1.0
    return df


@register("ret_log", n_params=1, lookback=lambda p: int(p[0]), description="Log return over n bars")
def ret_log(df: pd.DataFrame, p: tuple[float, ...]) -> pd.DataFrame:
    """Log return ``ln(close_t / close_{t-n})``."""
    n = int(p[0])
    df[_name("ret_log", p)] = np.log(df["close"] / df["close"].shift(n))
    return df


@register(
    "vol", n_params=1, lookback=lambda p: int(p[0]) + 1, description="Rolling annualised volatility of 1-bar log returns"
)
def vol(df: pd.DataFrame, p: tuple[float, ...]) -> pd.DataFrame:
    """Rolling standard deviation of 1-bar log returns, annualised by ``df.attrs['per_year']``."""
    n = int(p[0])
    per_year = float(df.attrs.get("per_year", 365.0))
    r = np.log(df["close"] / df["close"].shift(1))
    df[_name("vol", p)] = r.rolling(n, min_periods=n).std(ddof=1) * np.sqrt(per_year)
    return df


# --------------------------------------------------------------------------- trend


@register("sma", n_params=1, lookback=lambda p: int(p[0]), description="Simple moving average of close")
def sma(df: pd.DataFrame, p: tuple[float, ...]) -> pd.DataFrame:
    """Simple moving average."""
    n = int(p[0])
    df[_name("sma", p)] = df["close"].rolling(n, min_periods=n).mean()
    return df


@register("ema", n_params=1, lookback=lambda p: int(p[0]) * 3, description="Exponential moving average of close")
def ema(df: pd.DataFrame, p: tuple[float, ...]) -> pd.DataFrame:
    """Exponential moving average with span ``n`` (adjust=False, so it is strictly causal)."""
    n = int(p[0])
    df[_name("ema", p)] = df["close"].ewm(span=n, adjust=False, min_periods=n).mean()
    return df


@register(
    "macd",
    n_params=3,
    lookback=lambda p: int(p[1]) * 3 + int(p[2]),
    defaults=(12, 26, 9),
    description="MACD line, signal, histogram",
)
def macd(df: pd.DataFrame, p: tuple[float, ...]) -> pd.DataFrame:
    """MACD = EMA(fast) - EMA(slow); signal = EMA(MACD, sig); hist = MACD - signal."""
    fast, slow, sig = (int(x) for x in p)
    base = _name("macd", p)
    ema_fast = df["close"].ewm(span=fast, adjust=False, min_periods=fast).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False, min_periods=slow).mean()
    line = ema_fast - ema_slow
    signal = line.ewm(span=sig, adjust=False, min_periods=sig).mean()
    df[base] = line
    df[f"{base}_signal"] = signal
    df[f"{base}_hist"] = line - signal
    return df


@register("adx", n_params=1, lookback=lambda p: int(p[0]) * 3, defaults=(14,), description="Average directional index")
def adx(df: pd.DataFrame, p: tuple[float, ...]) -> pd.DataFrame:
    """Wilder's ADX using exponential smoothing with alpha = 1/n."""
    n = int(p[0])
    high, low, close = df["high"], df["low"], df["close"]
    up = high.diff()
    down = -low.diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    tr = pd.concat([high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / n, adjust=False, min_periods=n).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1 / n, adjust=False, min_periods=n).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    df[_name("adx", p)] = dx.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    return df


# --------------------------------------------------------------------------- mean reversion


@register(
    "boll",
    n_params=2,
    lookback=lambda p: int(p[0]),
    defaults=(20, 2),
    description="Bollinger bands: mid, upper, lower",
)
def boll(df: pd.DataFrame, p: tuple[float, ...]) -> pd.DataFrame:
    """Bollinger bands around an SMA with ``k`` standard deviations (population, ddof=0)."""
    n, k = int(p[0]), float(p[1])
    base = _name("boll", p)
    mid = df["close"].rolling(n, min_periods=n).mean()
    sd = df["close"].rolling(n, min_periods=n).std(ddof=0)
    df[f"{base}_mid"] = mid
    df[f"{base}_upper"] = mid + k * sd
    df[f"{base}_lower"] = mid - k * sd
    return df


@register("zscore", n_params=1, lookback=lambda p: int(p[0]), description="Z-score of close vs rolling mean")
def zscore(df: pd.DataFrame, p: tuple[float, ...]) -> pd.DataFrame:
    """``(close - rolling mean) / rolling std`` (ddof=0)."""
    n = int(p[0])
    mean = df["close"].rolling(n, min_periods=n).mean()
    sd = df["close"].rolling(n, min_periods=n).std(ddof=0)
    df[_name("zscore", p)] = (df["close"] - mean) / sd.replace(0, np.nan)
    return df


@register("rsi", n_params=1, lookback=lambda p: int(p[0]) * 3, defaults=(14,), description="Wilder RSI")
def rsi(df: pd.DataFrame, p: tuple[float, ...]) -> pd.DataFrame:
    """Wilder RSI with exponential smoothing alpha = 1/n."""
    n = int(p[0])
    delta = df["close"].diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    avg_loss = loss.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    out = out.where(avg_loss > 0, 100.0).where(avg_gain.notna(), np.nan)
    df[_name("rsi", p)] = out
    return df


# --------------------------------------------------------------------------- volume


@register("volz", n_params=1, lookback=lambda p: int(p[0]), description="Z-score of volume vs rolling window")
def volz(df: pd.DataFrame, p: tuple[float, ...]) -> pd.DataFrame:
    """Volume z-score."""
    n = int(p[0])
    mean = df["volume"].rolling(n, min_periods=n).mean()
    sd = df["volume"].rolling(n, min_periods=n).std(ddof=0)
    df[_name("volz", p)] = (df["volume"] - mean) / sd.replace(0, np.nan)
    return df


@register("dollar_volume", n_params=0, lookback=lambda p: 0, description="close * volume")
def dollar_volume(df: pd.DataFrame, p: tuple[float, ...]) -> pd.DataFrame:
    """Bar notional traded."""
    df["dollar_volume"] = df["close"] * df["volume"]
    return df


# --------------------------------------------------------------------------- regimes


@register(
    "vol_regime",
    n_params=2,
    lookback=lambda p: int(p[0]) + int(p[1]) + 1,
    defaults=(20, 250),
    description="Volatility tercile (0 low, 1 mid, 2 high) of vol_n within a trailing window",
)
def vol_regime(df: pd.DataFrame, p: tuple[float, ...]) -> pd.DataFrame:
    """Tercile of the current ``vol_n`` within the trailing ``m``-bar distribution of itself."""
    n, m = int(p[0]), int(p[1])
    per_year = float(df.attrs.get("per_year", 365.0))
    r = np.log(df["close"] / df["close"].shift(1))
    v = r.rolling(n, min_periods=n).std(ddof=1) * np.sqrt(per_year)
    rank = v.rolling(m, min_periods=max(10, m // 4)).rank(pct=True)
    tercile = pd.Series(np.select([rank < 1 / 3, rank < 2 / 3], [0.0, 1.0], default=2.0), index=df.index)
    df[_name("vol_regime", p)] = tercile.where(rank.notna(), np.nan)
    return df


@register(
    "trend_regime",
    n_params=1,
    lookback=lambda p: int(p[0]),
    defaults=(200,),
    description="1 when close is above the n-bar SMA, else 0",
)
def trend_regime(df: pd.DataFrame, p: tuple[float, ...]) -> pd.DataFrame:
    """Price above (1) or below (0) its long SMA."""
    n = int(p[0])
    s = df["close"].rolling(n, min_periods=n).mean()
    df[_name("trend_regime", p)] = (df["close"] > s).astype(float).where(s.notna(), np.nan)
    return df
