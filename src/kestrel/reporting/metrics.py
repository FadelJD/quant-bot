"""Performance metrics as pure functions over an equity curve and a trade log.

Formulas (``r`` is the per-bar simple return of equity, ``A`` bars per year):

- CAGR = ``(E_T / E_0) ** (A / n) - 1``
- Volatility = ``std(r, ddof=1) * sqrt(A)``
- Sharpe = ``mean(r) / std(r) * sqrt(A)`` with ``rf = 0``
- Sortino = ``mean(r) / std(min(r, 0)) * sqrt(A)``
- Max drawdown = ``min(E / cummax(E) - 1)``; duration = longest run of bars below the prior peak
- Calmar = ``CAGR / |max drawdown|``
- Hit rate = fraction of round-trip closing trades with positive realised PnL
- Profit factor = ``sum(wins) / |sum(losses)|``
- Turnover = ``(gross buys + gross sells) / 2 / mean equity`` per year
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def bar_returns(equity: pd.Series) -> pd.Series:
    """Simple per-bar returns of an equity series (first bar dropped)."""
    return equity.pct_change().dropna()


def sharpe(returns: pd.Series | np.ndarray, per_year: float) -> float:
    """Annualised Sharpe ratio with ``rf = 0``; 0 when there is no variance."""
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    if len(r) < 2:
        return 0.0
    sd = r.std(ddof=1)
    if sd == 0:
        return 0.0
    return float(r.mean() / sd * np.sqrt(per_year))


def sortino(returns: pd.Series | np.ndarray, per_year: float) -> float:
    """Annualised Sortino ratio (downside deviation over all bars)."""
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    if len(r) < 2:
        return 0.0
    downside = np.minimum(r, 0.0)
    dd = np.sqrt((downside**2).mean())
    if dd == 0:
        return 0.0
    return float(r.mean() / dd * np.sqrt(per_year))


def max_drawdown(equity: pd.Series | np.ndarray) -> tuple[float, int]:
    """Return ``(max drawdown as a negative fraction, longest drawdown duration in bars)``."""
    e = np.asarray(equity, dtype=float)
    if len(e) == 0:
        return 0.0, 0
    peak = np.maximum.accumulate(e)
    dd = e / peak - 1.0
    under = dd < 0
    longest = run = 0
    for flag in under:
        run = run + 1 if flag else 0
        longest = max(longest, run)
    return float(dd.min()), int(longest)


def cagr(equity: pd.Series | np.ndarray, per_year: float) -> float:
    """Compound annual growth rate."""
    e = np.asarray(equity, dtype=float)
    if len(e) < 2 or e[0] <= 0 or e[-1] <= 0:
        return 0.0
    years = (len(e) - 1) / per_year
    if years <= 0:
        return 0.0
    return float((e[-1] / e[0]) ** (1 / years) - 1.0)


def skew_kurt(returns: pd.Series | np.ndarray) -> tuple[float, float]:
    """Sample skewness and (non-excess) kurtosis of returns."""
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    if len(r) < 4:
        return 0.0, 3.0
    m = r.mean()
    sd = r.std(ddof=0)
    if sd == 0:
        return 0.0, 3.0
    z = (r - m) / sd
    return float((z**3).mean()), float((z**4).mean())


def trade_stats(trades: pd.DataFrame) -> dict[str, Any]:
    """Hit rate, average win and loss, profit factor over closing (sell) trades."""
    if trades.empty:
        return {"n_trades": 0, "n_round_trips": 0, "hit_rate": 0.0, "avg_win": 0.0, "avg_loss": 0.0, "profit_factor": 0.0}
    sells = trades[trades["side"] == "sell"]
    pnl = sells["realised_pnl"].to_numpy(dtype=float) if len(sells) else np.empty(0)
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    return {
        "n_trades": int(len(trades)),
        "n_round_trips": int(len(sells)),
        "hit_rate": float(len(wins) / len(pnl)) if len(pnl) else 0.0,
        "avg_win": float(wins.mean()) if len(wins) else 0.0,
        "avg_loss": float(losses.mean()) if len(losses) else 0.0,
        "profit_factor": float(wins.sum() / abs(losses.sum())) if len(losses) and losses.sum() != 0 else (float("inf") if len(wins) else 0.0),
    }


def performance_by_regime(returns: pd.Series, regimes: pd.DataFrame | None, per_year: float) -> dict[str, dict[str, float]]:
    """Sharpe and total return of the portfolio inside each regime label.

    Args:
        returns: Per-bar portfolio returns.
        regimes: Frame indexed like ``returns`` with one column per regime flag (e.g. ``vol_regime``).
        per_year: Bars per year.

    Returns:
        ``{"<column>=<value>": {"sharpe": .., "total_return": .., "n_bars": ..}}``.
    """
    out: dict[str, dict[str, float]] = {}
    if regimes is None or regimes.empty:
        return out
    aligned = regimes.reindex(returns.index)
    for col in aligned.columns:
        for val, group in returns.groupby(aligned[col]):
            if len(group) < 2:
                continue
            key = f"{col}={int(val) if float(val).is_integer() else val}"
            out[key] = {
                "sharpe": sharpe(group, per_year),
                "total_return": float((1 + group).prod() - 1),
                "n_bars": float(len(group)),
            }
    return out


def monthly_returns(equity: pd.Series) -> pd.DataFrame:
    """Year x month table of compounded returns."""
    if equity.empty:
        return pd.DataFrame()
    r = equity.resample("ME").last().pct_change().dropna()
    if r.empty:
        return pd.DataFrame()
    table = pd.DataFrame({"year": r.index.year, "month": r.index.month, "ret": r.to_numpy()})
    return table.pivot(index="year", columns="month", values="ret")


def compute_metrics(
    curve: pd.DataFrame,
    trades: pd.DataFrame,
    *,
    per_year: float,
    initial_cash: float,
    gross_buys: float = 0.0,
    gross_sells: float = 0.0,
    fees_paid: float = 0.0,
    slippage_paid: float = 0.0,
    clamped_shorts: int = 0,
    regimes: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Compute the full metrics dictionary used by reports and the validation layer."""
    equity = curve["equity"] if "equity" in curve else pd.Series(dtype=float)
    r = bar_returns(equity)
    mdd, mdd_dur = max_drawdown(equity)
    growth = cagr(equity, per_year)
    sk, ku = skew_kurt(r)
    n_bars = int(len(equity))
    years = max(n_bars / per_year, 1e-9)
    mean_eq = float(equity.mean()) if n_bars else initial_cash
    gross_pnl = float(equity.iloc[-1] - initial_cash + fees_paid + slippage_paid) if n_bars else 0.0
    ts = trade_stats(trades)
    exposure = float(curve["exposure"].mean()) if "exposure" in curve and n_bars else 0.0
    return {
        "n_bars": n_bars,
        "start": equity.index[0].isoformat() if n_bars else None,
        "end": equity.index[-1].isoformat() if n_bars else None,
        "initial_equity": float(initial_cash),
        "final_equity": float(equity.iloc[-1]) if n_bars else float(initial_cash),
        "total_return": float(equity.iloc[-1] / initial_cash - 1.0) if n_bars else 0.0,
        "cagr": growth,
        "volatility": float(r.std(ddof=1) * np.sqrt(per_year)) if len(r) > 1 else 0.0,
        "sharpe": sharpe(r, per_year),
        "sortino": sortino(r, per_year),
        "max_drawdown": mdd,
        "max_drawdown_duration_bars": mdd_dur,
        "calmar": float(growth / abs(mdd)) if mdd < 0 else 0.0,
        "skew": sk,
        "kurtosis": ku,
        **ts,
        "turnover_annual": float((gross_buys + gross_sells) / 2.0 / mean_eq / years) if mean_eq > 0 else 0.0,
        "exposure": exposure,
        "fees_paid": float(fees_paid),
        "slippage_paid": float(slippage_paid),
        "fees_pct_of_gross_pnl": float(fees_paid / abs(gross_pnl)) if gross_pnl != 0 else 0.0,
        "clamped_shorts": int(clamped_shorts),
        "by_regime": performance_by_regime(r, regimes, per_year),
    }
