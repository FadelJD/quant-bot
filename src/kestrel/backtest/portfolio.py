"""Portfolio accounting: cash, positions, realised and unrealised PnL, equity curve, trade log."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from kestrel.strategies.base import PositionView
from kestrel.types import OrderReason, Side


@dataclass
class PositionState:
    """Mutable position: quantity and average cost."""

    qty: float = 0.0
    avg_cost: float = 0.0


@dataclass(frozen=True)
class Trade:
    """One fill recorded in the trade log."""

    ts_signal: datetime
    ts_fill: datetime
    symbol: str
    side: Side
    qty: float
    price: float
    fee: float
    slippage_cost: float
    reason: OrderReason
    realised_pnl: float = 0.0


@dataclass
class Portfolio:
    """Cash plus positions, with an equity curve and a trade log."""

    initial_cash: float
    cash: float = field(init=False)
    positions: dict[str, PositionState] = field(default_factory=dict)
    trades: list[Trade] = field(default_factory=list)
    realised_pnl: float = 0.0
    fees_paid: float = 0.0
    slippage_paid: float = 0.0
    gross_buys: float = 0.0
    gross_sells: float = 0.0
    _curve: list[dict[str, float | datetime | int]] = field(default_factory=list)
    _peak: float = field(init=False)

    def __post_init__(self) -> None:
        """Start with all cash."""
        self.cash = float(self.initial_cash)
        self._peak = float(self.initial_cash)

    # ------------------------------------------------------------------ fills

    def apply_fill(
        self,
        *,
        ts_signal: datetime,
        ts_fill: datetime,
        symbol: str,
        side: Side,
        qty: float,
        price: float,
        fee: float,
        slippage_cost: float,
        reason: OrderReason,
    ) -> Trade:
        """Apply a fill to cash and positions and append it to the trade log."""
        pos = self.positions.setdefault(symbol, PositionState())
        realised = 0.0
        notional = qty * price
        if side == "buy":
            new_qty = pos.qty + qty
            pos.avg_cost = (pos.qty * pos.avg_cost + notional) / new_qty if new_qty > 0 else 0.0
            pos.qty = new_qty
            self.cash -= notional + fee
            self.gross_buys += notional
        else:
            qty = min(qty, pos.qty)
            notional = qty * price
            realised = qty * (price - pos.avg_cost) - fee
            pos.qty -= qty
            if pos.qty <= 1e-12:
                pos.qty = 0.0
                pos.avg_cost = 0.0
            self.cash += notional - fee
            self.gross_sells += notional
            self.realised_pnl += realised
        self.fees_paid += fee
        self.slippage_paid += slippage_cost
        trade = Trade(ts_signal, ts_fill, symbol, side, qty, price, fee, slippage_cost, reason, realised)
        self.trades.append(trade)
        return trade

    # ------------------------------------------------------------------ valuation

    def market_value(self, prices: dict[str, float]) -> float:
        """Sum of position values at ``prices``."""
        return sum(p.qty * prices.get(s, p.avg_cost) for s, p in self.positions.items() if p.qty > 0)

    def equity(self, prices: dict[str, float]) -> float:
        """Cash plus market value."""
        return self.cash + self.market_value(prices)

    def views(self, prices: dict[str, float]) -> dict[str, PositionView]:
        """Read-only position views for the strategy context."""
        return {
            s: PositionView(s, p.qty, p.avg_cost, p.qty * prices.get(s, p.avg_cost))
            for s, p in self.positions.items()
            if p.qty > 0
        }

    def qtys(self) -> dict[str, float]:
        """Symbol -> quantity for open positions."""
        return {s: p.qty for s, p in self.positions.items() if p.qty > 0}

    def mark(self, ts: datetime, prices: dict[str, float]) -> float:
        """Append a point to the equity curve and return equity."""
        eq = self.equity(prices)
        mv = self.market_value(prices)
        self._peak = max(self._peak, eq)
        dd = eq / self._peak - 1.0 if self._peak > 0 else 0.0
        self._curve.append(
            {
                "ts": ts,
                "equity": eq,
                "cash": self.cash,
                "exposure": mv / eq if eq > 0 else 0.0,
                "drawdown": dd,
                "n_positions": sum(1 for p in self.positions.values() if p.qty > 0),
            }
        )
        return eq

    def equity_curve(self) -> pd.DataFrame:
        """Equity curve indexed by bar timestamp (equity is marked at that bar's close)."""
        if not self._curve:
            return pd.DataFrame(columns=["equity", "cash", "exposure", "drawdown", "n_positions"]).rename_axis("ts")
        df = pd.DataFrame(self._curve).set_index("ts")
        df.index = pd.DatetimeIndex(df.index).tz_convert("UTC")
        df.index.name = "ts"
        return df

    def trade_log(self) -> pd.DataFrame:
        """Trade log as a DataFrame with the canonical column order."""
        cols = ["ts_signal", "ts_fill", "symbol", "side", "qty", "price", "fee", "slippage_cost", "reason", "realised_pnl"]
        if not self.trades:
            return pd.DataFrame(columns=cols)
        return pd.DataFrame([t.__dict__ for t in self.trades])[cols]
