"""Bitkub (Thai-licensed exchange) read-only adapter stub. Interface documented, not implemented."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

import pandas as pd

from kestrel.execution.protocol import Balance, Order, OrderRequest, Position, Quote
from kestrel.types import MarketMeta

_MSG = "BitkubAdapter is a v2 item: public read-only API at https://api.bitkub.com/api/market (no sandbox)."


class BitkubAdapter:
    """Placeholder so the owner can see the shape a THB-pair adapter would take."""

    market: Literal["crypto", "equities"] = "crypto"
    name = "bitkub:stub"

    def __init__(self) -> None:
        """Raise immediately: there is no Bitkub sandbox, so nothing here may trade."""
        raise NotImplementedError(_MSG)

    def is_open(self, ts: datetime) -> bool:  # pragma: no cover - unreachable
        """Not implemented."""
        raise NotImplementedError(_MSG)

    def next_open(self, ts: datetime) -> datetime:  # pragma: no cover
        """Not implemented."""
        raise NotImplementedError(_MSG)

    def get_bars(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> pd.DataFrame:  # pragma: no cover
        """Not implemented."""
        raise NotImplementedError(_MSG)

    def get_quote(self, symbol: str) -> Quote:  # pragma: no cover
        """Not implemented."""
        raise NotImplementedError(_MSG)

    def get_positions(self) -> list[Position]:  # pragma: no cover
        """Not implemented."""
        raise NotImplementedError(_MSG)

    def get_balance(self) -> Balance:  # pragma: no cover
        """Not implemented."""
        raise NotImplementedError(_MSG)

    def place_order(self, req: OrderRequest) -> Order:  # pragma: no cover
        """Not implemented."""
        raise NotImplementedError(_MSG)

    def cancel_order(self, order_id: str) -> None:  # pragma: no cover
        """Not implemented."""
        raise NotImplementedError(_MSG)

    def get_order(self, order_id: str) -> Order:  # pragma: no cover
        """Not implemented."""
        raise NotImplementedError(_MSG)

    def get_open_orders(self) -> list[Order]:  # pragma: no cover
        """Not implemented."""
        raise NotImplementedError(_MSG)

    def market_meta(self, symbol: str) -> MarketMeta:  # pragma: no cover
        """Not implemented."""
        raise NotImplementedError(_MSG)
