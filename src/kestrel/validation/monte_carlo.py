"""Monte Carlo on trade order: the sequence is luck, the drawdown distribution is the risk."""

from __future__ import annotations

from typing import Any

import numpy as np


def monte_carlo_drawdown(
    trade_pnl: np.ndarray,
    *,
    initial_equity: float,
    n_resamples: int = 1000,
    ruin_drawdown: float = 0.15,
    seed: int = 42,
) -> dict[str, Any]:
    """Shuffle the trade sequence and report the drawdown distribution.

    Args:
        trade_pnl: Realised PnL per closing trade, in currency.
        initial_equity: Starting equity for the simulated paths.
        n_resamples: Number of shuffles.
        ruin_drawdown: Drawdown fraction counted as ruin.
        seed: RNG seed.

    Returns:
        ``p05_max_drawdown`` (the 5th percentile, i.e. the worse tail), ``median_max_drawdown``,
        ``probability_of_ruin``, ``n_trades``.
    """
    pnl = np.asarray(trade_pnl, dtype=float)
    pnl = pnl[~np.isnan(pnl)]
    if len(pnl) < 2 or initial_equity <= 0:
        return {"p05_max_drawdown": 0.0, "median_max_drawdown": 0.0, "probability_of_ruin": 0.0, "n_trades": int(len(pnl))}
    rng = np.random.default_rng(seed)
    mdds = np.empty(n_resamples)
    for i in range(n_resamples):
        path = initial_equity + np.cumsum(rng.permutation(pnl))
        path = np.concatenate([[initial_equity], path])
        peak = np.maximum.accumulate(path)
        mdds[i] = float((path / peak - 1.0).min())
    return {
        "p05_max_drawdown": float(np.percentile(mdds, 5)),
        "median_max_drawdown": float(np.median(mdds)),
        "probability_of_ruin": float((mdds <= -ruin_drawdown).mean()),
        "n_trades": int(len(pnl)),
    }
