"""Block bootstrap confidence interval on the annualised Sharpe ratio."""

from __future__ import annotations

from typing import Any

import numpy as np

from kestrel.reporting.metrics import sharpe


def block_bootstrap_sharpe(
    returns: np.ndarray,
    *,
    per_year: float,
    block: int = 20,
    n_resamples: int = 1000,
    seed: int = 42,
) -> dict[str, Any]:
    """Resample contiguous blocks of returns and return the 2.5 and 97.5 percentiles of Sharpe."""
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    n = len(r)
    if n < max(block, 10):
        return {"sharpe": sharpe(r, per_year), "ci_low": 0.0, "ci_high": 0.0, "n_obs": int(n)}
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n / block))
    samples = np.empty(n_resamples)
    for i in range(n_resamples):
        starts = rng.integers(0, n - block + 1, size=n_blocks)
        idx = np.concatenate([np.arange(s, s + block) for s in starts])[:n]
        samples[i] = sharpe(r[idx], per_year)
    return {
        "sharpe": sharpe(r, per_year),
        "ci_low": float(np.percentile(samples, 2.5)),
        "ci_high": float(np.percentile(samples, 97.5)),
        "n_obs": int(n),
    }
