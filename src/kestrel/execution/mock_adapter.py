"""Deterministic, scriptable mock adapter for tests, the backtester, and simulated paper runs.

Scenarios inject rejections, partial fills, timeouts (orders that stay open), and stale quotes,
keyed by ``client_order_id`` prefix, symbol, or call count. Prices come from a price feed
callable so a SimClock-driven run can advance bar by bar.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import pandas as pd
import yaml

from kestrel.clock import Clock, ensure_utc
from kestrel.data.calendar import MarketCalendar, calendar_for
from kestrel.errors import AdapterError
from kestrel.execution.protocol import Balance, Order, OrderRequest, Position, Quote
from kestrel.types import MarketMeta, default_meta


@dataclass
class Scenario:
    """Scripted behaviours. All lists are consumed in order; empty means normal behaviour."""

    reject_symbols: list[str] = field(default_factory=list)
    reject_every_nth: int = 0
    partial_fill_fraction: float = 1.0
    timeout_symbols: list[str] = field(default_factory=list)
    """Orders for these symbols stay ``open`` until :meth:`MockAdapter.settle_open` is called."""
    stale_quote_seconds: int = 0
    fail_calls: list[str] = field(default_factory=list)
    """Method names that raise ``AdapterError`` on their next call (consumed one at a time)."""
    fee_rate: float = 0.001

    @classmethod
    def from_yaml(cls, path: Path) -> Scenario:
        """Load a scenario from YAML."""
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls(**raw)


class MockAdapter:
    """In-memory broker with a scripted scenario."""

    market: Literal["crypto", "equities"]
    name = "mock"

    def __init__(
        self,
        *,
        market: Literal["crypto", "equities"] = "crypto",
        clock: Clock,
        price_feed: Callable[[str, datetime], float],
        bars: dict[str, pd.DataFrame] | None = None,
        initial_cash: float = 100_000.0,
        scenario: Scenario | None = None,
        calendar: MarketCalendar | None = None,
        meta: dict[str, MarketMeta] | None = None,
    ) -> None:
        """Create a mock broker.

        Args:
            market: Which market rules to mimic.
            clock: Time source.
            price_feed: ``(symbol, ts) -> price`` used for fills and marks.
            bars: Optional frames served by :meth:`get_bars`.
            initial_cash: Starting cash.
            scenario: Scripted behaviours.
            calendar: Market calendar; defaults by market.
            meta: Per-symbol metadata; defaults by market.
        """
        self.market = market
        self.clock = clock
        self.price_feed = price_feed
        self.bars = bars or {}
        self.cash = Decimal(str(initial_cash))
        self.scenario = scenario or Scenario()
        self.calendar = calendar or calendar_for(market)
        self._meta = meta or {}
        self._positions: dict[str, tuple[Decimal, Decimal]] = {}
        self._orders: dict[str, Order] = {}
        self._by_client: dict[str, str] = {}
        self._n = 0
        self.calls: list[str] = []

    # ------------------------------------------------------------------ helpers

    def _maybe_fail(self, method: str) -> None:
        self.calls.append(method)
        if self.scenario.fail_calls and self.scenario.fail_calls[0] == method:
            self.scenario.fail_calls.pop(0)
            raise AdapterError(f"mock: scripted failure in {method}")

    def _price(self, symbol: str) -> Decimal:
        return Decimal(str(self.price_feed(symbol, self.clock.now())))

    def set_position(self, symbol: str, qty: float, avg_cost: float) -> None:
        """Force a broker-side position (to simulate drift)."""
        self._positions[symbol] = (Decimal(str(qty)), Decimal(str(avg_cost)))

    # ------------------------------------------------------------------ protocol

    def is_open(self, ts: datetime) -> bool:
        """Delegate to the calendar."""
        return self.calendar.is_open(ts)

    def next_open(self, ts: datetime) -> datetime:
        """Delegate to the calendar."""
        return self.calendar.next_open(ts)

    def get_bars(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> pd.DataFrame:
        """Slice the configured frames."""
        self._maybe_fail("get_bars")
        frame = self.bars.get(symbol)
        if frame is None:
            raise AdapterError(f"mock: no bars for {symbol}")
        s, e = pd.Timestamp(ensure_utc(start)), pd.Timestamp(ensure_utc(end))
        return frame[(frame.index >= s) & (frame.index <= e)]

    def get_quote(self, symbol: str) -> Quote:
        """Quote around the feed price with a 2 bps half-spread; possibly stale."""
        self._maybe_fail("get_quote")
        p = self._price(symbol)
        ts = self.clock.now() - timedelta(seconds=self.scenario.stale_quote_seconds)
        return Quote(symbol, p * Decimal("0.9998"), p * Decimal("1.0002"), ts)

    def get_positions(self) -> list[Position]:
        """Open positions marked at the feed price."""
        self._maybe_fail("get_positions")
        out = []
        for s, (q, c) in sorted(self._positions.items()):
            if q > 0:
                out.append(Position(s, q, c, q * self._price(s)))
        return out

    def get_balance(self) -> Balance:
        """Cash plus marked positions."""
        self._maybe_fail("get_balance")
        mv = sum((q * self._price(s) for s, (q, _) in self._positions.items() if q > 0), Decimal(0))
        return Balance(self.cash, self.cash + mv)

    def place_order(self, req: OrderRequest) -> Order:
        """Fill immediately at the feed price unless the scenario says otherwise. Idempotent."""
        self._maybe_fail("place_order")
        if req.client_order_id in self._by_client:
            return self._orders[self._by_client[req.client_order_id]]
        self._n += 1
        now = self.clock.now()
        oid = f"mock-{self._n}"
        rejected = req.symbol in self.scenario.reject_symbols or (
            self.scenario.reject_every_nth and self._n % self.scenario.reject_every_nth == 0
        )
        if rejected:
            order = Order(oid, req.client_order_id, req.symbol, req.side, req.qty, Decimal(0), None, "rejected", now, now)
        elif req.symbol in self.scenario.timeout_symbols:
            order = Order(oid, req.client_order_id, req.symbol, req.side, req.qty, Decimal(0), None, "open", now, now)
        else:
            order = self._fill(oid, req, now)
        self._orders[oid] = order
        self._by_client[req.client_order_id] = oid
        return order

    def _fill(self, oid: str, req: OrderRequest, now: datetime) -> Order:
        price = self._price(req.symbol)
        qty = req.qty * Decimal(str(self.scenario.partial_fill_fraction))
        fee = qty * price * Decimal(str(self.scenario.fee_rate))
        q0, c0 = self._positions.get(req.symbol, (Decimal(0), Decimal(0)))
        if req.side == "buy":
            cost = qty * price + fee
            if cost > self.cash:
                return Order(oid, req.client_order_id, req.symbol, req.side, req.qty, Decimal(0), None, "rejected", now, now)
            self.cash -= cost
            new_q = q0 + qty
            self._positions[req.symbol] = (new_q, (q0 * c0 + qty * price) / new_q if new_q else Decimal(0))
        else:
            qty = min(qty, q0)
            self.cash += qty * price - fee
            self._positions[req.symbol] = (q0 - qty, c0 if q0 - qty > 0 else Decimal(0))
        status: Any = "filled" if qty == req.qty else "partially_filled"
        return Order(oid, req.client_order_id, req.symbol, req.side, req.qty, qty, price, status, now, now, fee)

    def settle_open(self) -> None:
        """Fill every open order (simulates a delayed fill after a timeout)."""
        for oid, o in list(self._orders.items()):
            if o.status == "open":
                req = OrderRequest(o.symbol, o.side, o.qty, o.client_order_id)
                self._orders[oid] = self._fill(oid, req, self.clock.now())

    def cancel_order(self, order_id: str) -> None:
        """Cancel an open order."""
        self._maybe_fail("cancel_order")
        o = self._orders.get(order_id)
        if o is None:
            raise AdapterError(f"mock: unknown order {order_id}")
        if not o.terminal:
            self._orders[order_id] = Order(o.order_id, o.client_order_id, o.symbol, o.side, o.qty, o.filled_qty, o.avg_fill_price, "cancelled", o.submitted_at, self.clock.now(), o.fee)

    def get_order(self, order_id: str) -> Order:
        """Look up an order."""
        self._maybe_fail("get_order")
        if order_id not in self._orders:
            raise AdapterError(f"mock: unknown order {order_id}")
        return self._orders[order_id]

    def get_open_orders(self) -> list[Order]:
        """Non-terminal orders."""
        self._maybe_fail("get_open_orders")
        return [o for o in self._orders.values() if not o.terminal]

    def market_meta(self, symbol: str) -> MarketMeta:
        """Configured or default metadata."""
        return self._meta.get(symbol, default_meta(symbol, self.market))
