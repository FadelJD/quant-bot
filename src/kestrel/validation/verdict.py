"""Verdict rules: ``pass | caution | fail`` with reasons."""

from __future__ import annotations

from typing import Any

from kestrel.config import ValidationConfig


def decide(checks: dict[str, Any], cfg: ValidationConfig) -> tuple[str, list[str]]:
    """Apply the verdict rules to the collected checks.

    ``fail`` if deflated Sharpe < ``dsr_fail``, OOS/IS ratio < ``oos_is_ratio_fail``, fewer than
    ``min_trades`` trades, or the implausibility/memorisation pattern is matched. ``caution`` if any
    single check is marginal. ``pass`` otherwise.
    """
    reasons: list[str] = []
    fail = False

    n_trades = checks.get("n_trades", 0)
    if n_trades < cfg.min_trades:
        fail = True
        reasons.append(f"fail: only {n_trades} trades (< {cfg.min_trades})")

    dsr = checks.get("dsr")
    if dsr is not None:
        if dsr < cfg.dsr_fail:
            fail = True
            reasons.append(f"fail: deflated Sharpe probability {dsr:.2f} < {cfg.dsr_fail:.2f}")
        elif dsr < cfg.dsr_caution:
            reasons.append(f"caution: deflated Sharpe probability {dsr:.2f} < {cfg.dsr_caution:.2f}")

    ratio = checks.get("oos_is_ratio")
    if ratio is not None and checks.get("n_windows", 0) > 0:
        if ratio < cfg.oos_is_ratio_fail:
            fail = True
            reasons.append(f"fail: OOS/IS Sharpe ratio {ratio:.2f} < {cfg.oos_is_ratio_fail:.2f}")
        elif ratio < cfg.oos_is_ratio_caution:
            reasons.append(f"caution: OOS/IS Sharpe ratio {ratio:.2f} < {cfg.oos_is_ratio_caution:.2f}")
        frac = checks.get("fraction_positive_oos", 1.0)
        if frac < 0.5:
            reasons.append(f"caution: only {frac:.0%} of walk-forward windows positive out of sample")

    if checks.get("implausible"):
        fail = True
        reasons.append("fail: " + str(checks.get("implausible_reason", "implausible performance")))
    if checks.get("memorisation"):
        fail = True
        reasons.append("fail: " + str(checks.get("memorisation_reason", "edge vanishes on resampled data")))

    if checks.get("sharp_peak"):
        reasons.append("caution: parameter sensitivity shows a sharp peak (neighbours lose > 50% of Sharpe)")
    ci_low = checks.get("bootstrap_ci_low")
    if ci_low is not None and checks.get("bootstrap_n_obs", 0) > 0 and ci_low < 0:
        reasons.append(f"caution: bootstrap 95% CI on Sharpe includes zero (low {ci_low:.2f})")
    ruin = checks.get("probability_of_ruin")
    if ruin is not None and ruin > cfg.ruin_probability_caution:
        reasons.append(f"caution: Monte Carlo probability of ruin {ruin:.1%} > {cfg.ruin_probability_caution:.0%}")

    if fail:
        return "fail", reasons
    if reasons:
        return "caution", reasons
    return "pass", ["all checks passed"]
