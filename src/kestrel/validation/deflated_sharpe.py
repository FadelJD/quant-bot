"""Probabilistic and deflated Sharpe ratio (Bailey and López de Prado, 2014).

All Sharpe ratios here are per-bar (not annualised). ``probabilistic_sharpe`` gives
``P(true SR > sr_star)`` given skew, kurtosis and sample length; ``deflated_sharpe`` sets
``sr_star`` to the expected maximum Sharpe among ``n_trials`` random strategies.
"""

from __future__ import annotations

import math
from statistics import NormalDist

_N = NormalDist()
EULER_GAMMA = 0.5772156649015329


def probabilistic_sharpe(sr: float, sr_star: float, n_obs: int, skew: float, kurt: float) -> float:
    """``PSR = Phi( (SR - SR*) sqrt(T-1) / sqrt(1 - skew*SR + (kurt-1)/4 * SR^2) )``."""
    if n_obs < 3:
        return 0.0
    denom_sq = 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr
    if denom_sq <= 0:
        return 1.0 if sr > sr_star else 0.0
    z = (sr - sr_star) * math.sqrt(n_obs - 1) / math.sqrt(denom_sq)
    return float(_N.cdf(z))


def expected_max_sharpe(n_trials: int, sr_variance: float) -> float:
    """``E[max SR] = sqrt(V) * ((1-g) Z(1-1/N) + g Z(1-1/(N e)))`` with ``g`` Euler's constant."""
    if n_trials <= 1 or sr_variance <= 0:
        return 0.0
    a = _N.inv_cdf(1.0 - 1.0 / n_trials)
    b = _N.inv_cdf(1.0 - 1.0 / (n_trials * math.e))
    return math.sqrt(sr_variance) * ((1 - EULER_GAMMA) * a + EULER_GAMMA * b)


def deflated_sharpe(
    sr: float,
    *,
    n_trials: int,
    n_obs: int,
    skew: float,
    kurt: float,
    sr_variance: float | None = None,
) -> dict[str, float]:
    """Return the deflated Sharpe probability and its inputs.

    Args:
        sr: Observed per-bar Sharpe of the selected strategy.
        n_trials: Number of strategy variants tried.
        n_obs: Number of return observations.
        skew: Sample skewness of returns.
        kurt: Sample (non-excess) kurtosis of returns.
        sr_variance: Variance of the trials' Sharpe ratios. When unknown, the estimator variance
            of a single Sharpe under the null, ``(1 - skew*SR + (kurt-1)/4 SR^2) / (T-1)``, is used.

    Returns:
        ``{"dsr": probability, "sr_star": expected max SR, "psr_vs_zero": PSR with SR*=0}``.
    """
    if sr_variance is None:
        sr_variance = max(1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr, 1e-12) / max(n_obs - 1, 1)
    sr_star = expected_max_sharpe(n_trials, sr_variance)
    return {
        "dsr": probabilistic_sharpe(sr, sr_star, n_obs, skew, kurt),
        "sr_star": sr_star,
        "psr_vs_zero": probabilistic_sharpe(sr, 0.0, n_obs, skew, kurt),
        "n_trials": float(n_trials),
    }
