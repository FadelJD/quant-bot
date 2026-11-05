"""Hard limits applied to target weights and the resulting orders. All pure."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from kestrel.config import RiskConfig
from kestrel.types import MarketMeta, OrderIntent


@dataclass
class LimitReport:
    """What the limits changed, for the log and the ``clamped_shorts`` metric."""

    clamped_shorts: int = 0
    clamped_weights: int = 0
    scaled_gross: bool = False
    dropped_small: int = 0
    dropped_excess: int = 0
    notes: list[str] = field(default_factory=list)


def clamp_weights(targets: Mapping[str, float], cfg: RiskConfig, report: LimitReport) -> dict[str, float]:
    """Clamp negatives to 0, cap per symbol, and scale gross exposure pro rata."""
    out: dict[str, float] = {}
    for s, w in targets.items():
        if w < 0:
            report.clamped_shorts += 1
            continue
        if w > cfg.max_weight_per_symbol:
            report.clamped_weights += 1
            w = cfg.max_weight_per_symbol
        if w > 0:
            out[s] = w
    total = sum(out.values())
    if total > cfg.max_gross_exposure + 1e-12 and total > 0:
        report.scaled_gross = True
        scale = cfg.max_gross_exposure / total
        out = {s: w * scale for s, w in out.items()}
    return out


def weights_to_orders(
    weights: Mapping[str, float],
    *,
    equity: float,
    positions: Mapping[str, float],
    prices: Mapping[str, float],
    meta: Mapping[str, MarketMeta],
    cfg: RiskConfig,
    report: LimitReport,
    reason: str = "signal",
) -> list[OrderIntent]:
    """Turn target weights into delta orders, honouring lot steps, minimum notional and order caps.

    Args:
        weights: Post-clamp target weights.
        equity: Current equity.
        positions: Symbol -> current quantity.
        prices: Symbol -> reference price (last close).
        meta: Symbol -> market metadata.
        cfg: Risk config.
        report: Mutated with what was dropped.
        reason: Order reason label.

    Returns:
        Orders sorted largest-notional first, at most ``cfg.max_orders_per_bar``.
    """
    orders: list[OrderIntent] = []
    symbols = set(weights) | {s for s, q in positions.items() if q > 0}
    for s in sorted(symbols):
        price = prices.get(s)
        if price is None or price <= 0:
            continue
        target_notional = weights.get(s, 0.0) * equity
        current_qty = positions.get(s, 0.0)
        delta_notional = target_notional - current_qty * price
        m = meta.get(s, MarketMeta(symbol=s))
        side = "buy" if delta_notional > 0 else "sell"
        qty = m.round_qty(abs(delta_notional) / price)
        if side == "sell" and weights.get(s, 0.0) == 0.0:
            qty = current_qty  # full exit: never leave dust behind
        if qty <= 0:
            continue
        if qty * price < m.min_notional:
            if side == "sell" and weights.get(s, 0.0) == 0.0 and current_qty > 0:
                orders.append(OrderIntent(s, "sell", qty, price, reason))  # type: ignore[arg-type]
                continue
            report.dropped_small += 1
            continue
        orders.append(OrderIntent(s, side, qty, price, reason))  # type: ignore[arg-type]
    orders.sort(key=lambda o: (-o.notional, o.symbol))
    if len(orders) > cfg.max_orders_per_bar:
        report.dropped_excess += len(orders) - cfg.max_orders_per_bar
        orders = orders[: cfg.max_orders_per_bar]
    return orders


def apply_limits(
    targets: Mapping[str, float],
    *,
    equity: float,
    positions: Mapping[str, float],
    prices: Mapping[str, float],
    meta: Mapping[str, MarketMeta],
    cfg: RiskConfig,
    reason: str = "signal",
) -> tuple[list[OrderIntent], LimitReport]:
    """Clamp weights then convert to orders. Convenience wrapper used by property tests."""
    report = LimitReport()
    weights = clamp_weights(targets, cfg, report)
    orders = weights_to_orders(
        weights, equity=equity, positions=positions, prices=prices, meta=meta, cfg=cfg, report=report, reason=reason
    )
    return orders, report
