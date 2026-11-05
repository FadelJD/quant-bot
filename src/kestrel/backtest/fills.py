"""Fill, fee, and slippage models.

``slippage = min(cap, base_bps/1e4 + impact_k * participation)`` where participation is the
order notional over the bar's dollar volume. Orders above ``max_participation`` of bar volume
fill only that fraction; the remainder is cancelled. Quantities are rounded down to the lot
step and dropped below the minimum notional.
"""

from __future__ import annotations

from dataclasses import dataclass

from kestrel.config import FeeConfig, SlippageConfig
from kestrel.types import MarketMeta, OrderIntent


@dataclass(frozen=True)
class FillResult:
    """Outcome of applying the fill model to one order on one bar."""

    qty: float
    price: float
    fee: float
    slippage_cost: float
    cancelled_qty: float
    reason: str = ""

    @property
    def filled(self) -> bool:
        """Whether any quantity filled."""
        return self.qty > 0


@dataclass(frozen=True)
class FillModel:
    """Deterministic fill model parameterised by fee and slippage config."""

    fees: FeeConfig
    slippage: SlippageConfig
    max_participation: float = 0.05

    def slippage_fraction(self, notional: float, bar_dollar_volume: float) -> float:
        """Slippage as a fraction of price for an order of ``notional`` on a bar of given liquidity."""
        base = self.slippage.base_bps / 1e4
        cap = self.slippage.cap_bps / 1e4
        if bar_dollar_volume <= 0:
            return cap
        impact = self.slippage.impact_k * (notional / bar_dollar_volume)
        return min(cap, base + impact)

    def fill(
        self,
        order: OrderIntent,
        *,
        ref_price: float,
        bar_volume: float,
        meta: MarketMeta,
    ) -> FillResult:
        """Fill an order at ``ref_price`` (the next bar's open) adjusted for slippage and costs.

        Args:
            order: The approved order.
            ref_price: Reference price (next open).
            bar_volume: Volume of the fill bar in base units.
            meta: Lot and minimum-notional rules for the symbol.

        Returns:
            A :class:`FillResult`; ``qty`` is 0 when nothing fills.
        """
        max_qty = self.max_participation * bar_volume if bar_volume > 0 else order.qty
        qty = min(order.qty, max_qty)
        qty = meta.round_qty(qty)
        cancelled = order.qty - qty
        if qty <= 0 or qty * ref_price < meta.min_notional:
            return FillResult(0.0, ref_price, 0.0, 0.0, order.qty, "below_min_notional_or_lot")
        slip = self.slippage_fraction(qty * ref_price, ref_price * bar_volume)
        price = ref_price * (1 + slip) if order.side == "buy" else ref_price * (1 - slip)
        fee = qty * price * (self.fees.rate_bps / 1e4)
        slippage_cost = qty * ref_price * slip
        reason = "partial_fill_participation_cap" if cancelled > 1e-12 else ""
        return FillResult(qty, price, fee, slippage_cost, max(cancelled, 0.0), reason)
