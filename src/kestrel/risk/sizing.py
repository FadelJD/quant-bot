"""Position sizing: fixed fraction or volatility targeting. Pure functions over weights."""

from __future__ import annotations

from collections.abc import Mapping


def size_fixed_fraction(targets: Mapping[str, float], max_gross: float) -> dict[str, float]:
    """Use weights as given, scaled down pro rata if their sum exceeds ``max_gross``."""
    clean = {s: max(w, 0.0) for s, w in targets.items() if w > 0}
    total = sum(clean.values())
    if total > max_gross and total > 0:
        scale = max_gross / total
        clean = {s: w * scale for s, w in clean.items()}
    return clean


def size_vol_target(
    targets: Mapping[str, float],
    vols: Mapping[str, float],
    *,
    target_vol: float,
    max_weight: float,
    max_gross: float,
) -> dict[str, float]:
    """Scale each position so its volatility contribution matches an equal share of ``target_vol``.

    ``w_i = (target_vol / n) / vol_i`` capped at ``max_weight``, then the gross is capped at
    ``max_gross`` pro rata. Symbols with unknown or zero volatility get the raw weight capped.

    Args:
        targets: Strategy target weights (used for membership and relative scaling).
        vols: Annualised realised volatility per symbol.
        target_vol: Annualised portfolio volatility target.
        max_weight: Per-symbol cap.
        max_gross: Gross exposure cap.

    Returns:
        Sized weights.
    """
    active = {s: w for s, w in targets.items() if w > 0}
    if not active:
        return {}
    n = len(active)
    out: dict[str, float] = {}
    for s, raw in active.items():
        v = vols.get(s)
        if v is None or v != v or v <= 0:
            w = raw
        else:
            w = (target_vol / n) / v
        out[s] = min(w, max_weight)
    total = sum(out.values())
    if total > max_gross and total > 0:
        out = {s: w * max_gross / total for s, w in out.items()}
    return out
