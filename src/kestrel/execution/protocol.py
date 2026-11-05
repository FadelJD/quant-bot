"""The MarketAdapter protocol and its value types. ``live/`` depends on nothing else here."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol

import pandas as pd

from kestrel.types import MarketMeta, Side

OrderStatus = Literal["new", "open", "filled", "partially_filled", "cancelled", "rejected", "expired"]


@dataclass(frozen=True)
class Quote:
    """Best bid and ask at ``ts``."""

    symbol: str
    bid: Decimal
    ask: Decimal
    ts: datetime


@dataclass(frozen=True)
class Position:
    """A broker-reported position."""

    symbol: str
    qty: Decimal
    avg_cost: Decimal
    market_value: Decimal


@dataclass(frozen=True)
class Balance:
    """Broker-reported cash and equity."""

    cash: Decimal
    equity: Decimal
    currency: str = "USD"


@dataclass(frozen=True)
class OrderRequest:
    """What we ask the broker to do. ``client_order_id`` makes retries idempotent."""

    symbol: str
    side: Side
    qty: Decimal
    client_order_id: str
    order_type: Literal["market", "limit"] = "market"
    limit_price: Decimal | None = None
    time_in_force: Literal["day", "gtc", "ioc"] = "day"


@dataclass(frozen=True)
class Order:
    """Broker state of an order."""

    order_id: str
    client_order_id: str
    symbol: str
    side: Side
    qty: Decimal
    filled_qty: Decimal
    avg_fill_price: Decimal | None
    status: OrderStatus
    submitted_at: datetime
    updated_at: datetime
    fee: Decimal = Decimal(0)

    @property
    def terminal(self) -> bool:
        """Whether no further changes can happen."""
        return self.status in {"filled", "cancelled", "rejected", "expired"}


class MarketAdapter(Protocol):
    """Everything the live loop needs from a broker or exchange."""

    market: Literal["crypto", "equities"]
    name: str

    def is_open(self, ts: datetime) -> bool:
        """Whether the market trades at ``ts``."""
        ...

    def next_open(self, ts: datetime) -> datetime:
        """Next session open after ``ts``."""
        ...

    def get_bars(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> pd.DataFrame:
        """Canonical OHLCV frame for the window."""
        ...

    def get_quote(self, symbol: str) -> Quote:
        """Best bid and ask."""
        ...

    def get_positions(self) -> list[Position]:
        """Open positions (source of truth)."""
        ...

    def get_balance(self) -> Balance:
        """Cash and equity (source of truth)."""
        ...

    def place_order(self, req: OrderRequest) -> Order:
        """Submit an order; a repeated ``client_order_id`` returns the existing order."""
        ...

    def cancel_order(self, order_id: str) -> None:
        """Cancel if still open."""
        ...

    def get_order(self, order_id: str) -> Order:
        """Current state of an order."""
        ...

    def get_open_orders(self) -> list[Order]:
        """Orders not yet terminal."""
        ...

    def market_meta(self, symbol: str) -> MarketMeta:
        """Minimum notional, lot step, tick size, fee."""
        ...
