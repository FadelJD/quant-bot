"""Shared value types used across layers (kept dependency-free so import boundaries stay clean)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Side = Literal["buy", "sell"]
OrderReason = Literal["signal", "rebalance", "risk_exit", "eod_flat"]


@dataclass(frozen=True)
class MarketMeta:
    """Per-symbol trading rules, frozen from the adapter's market metadata."""

    symbol: str
    min_notional: float = 10.0
    lot_step: float = 1e-6
    tick_size: float = 0.01
    taker_fee: float = 0.001

    def round_qty(self, qty: float) -> float:
        """Round a quantity down to the lot step (never up, never below zero)."""
        if self.lot_step <= 0:
            return max(qty, 0.0)
        steps = int(qty / self.lot_step + 1e-9)
        return max(steps * self.lot_step, 0.0)


@dataclass(frozen=True)
class OrderIntent:
    """An order the risk layer has approved but nothing has executed yet."""

    symbol: str
    side: Side
    qty: float
    est_price: float
    reason: OrderReason = "signal"

    @property
    def notional(self) -> float:
        """Estimated notional at the reference price."""
        return self.qty * self.est_price


def default_meta(symbol: str, market: str) -> MarketMeta:
    """Conservative default metadata when an adapter has not supplied any."""
    if market == "equities":
        return MarketMeta(symbol=symbol, min_notional=1.0, lot_step=1e-6, tick_size=0.01, taker_fee=0.0)
    return MarketMeta(symbol=symbol, min_notional=10.0, lot_step=1e-5, tick_size=0.01, taker_fee=0.001)
