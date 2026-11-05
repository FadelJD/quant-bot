"""Alpaca adapter, paper only. The base URL must be the paper endpoint before any network call."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

import pandas as pd

from kestrel.clock import ensure_utc
from kestrel.data.calendar import CryptoCalendar, NyseCalendar
from kestrel.data.fetchers import AlpacaSource
from kestrel.errors import AdapterError
from kestrel.execution.protocol import Balance, Order, OrderRequest, Position, Quote
from kestrel.execution.safety import ALPACA_PAPER_URL, assert_paper_endpoint
from kestrel.types import MarketMeta


class AlpacaAdapter:
    """US equities (and crypto) paper trading through ``alpaca-py``."""

    def __init__(
        self,
        key_id: str,
        secret: str,
        *,
        market: Literal["crypto", "equities"] = "equities",
        base_url: str = ALPACA_PAPER_URL,
        trading_client: Any | None = None,
        data_client: Any | None = None,
    ) -> None:
        """Create the adapter; ``base_url`` is validated against the paper allowlist first."""
        assert_paper_endpoint(base_url, provider="alpaca")
        self.market = market
        self.name = "alpaca:paper"
        self.base_url = base_url
        if trading_client is None:
            from alpaca.trading.client import TradingClient

            trading_client = TradingClient(key_id, secret, paper=True, url_override=base_url)
        self.client = trading_client
        self._source = AlpacaSource(market, key_id, secret, client=data_client)
        self.calendar = NyseCalendar() if market == "equities" else CryptoCalendar()

    @staticmethod
    def _translate(exc: BaseException) -> AdapterError:
        msg = str(exc)
        if "forbidden" in msg.lower() or "403" in msg:
            return AdapterError("provider alpaca blocked or key rejected: " + msg)
        return AdapterError(msg)

    def is_open(self, ts: datetime) -> bool:
        """Regular session check via the calendar (never submit outside regular hours)."""
        return self.calendar.is_open(ts)

    def next_open(self, ts: datetime) -> datetime:
        """Next session open."""
        return self.calendar.next_open(ts)

    def get_bars(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> pd.DataFrame:
        """Bars through the market data client."""
        return self._source.fetch(symbol, timeframe, start, end)

    def get_quote(self, symbol: str) -> Quote:
        """Latest quote from the data client."""
        try:
            if self.market == "equities":
                from alpaca.data.requests import StockLatestQuoteRequest

                q = self._source.client.get_stock_latest_quote(StockLatestQuoteRequest(symbol_or_symbols=symbol))[symbol]
            else:
                from alpaca.data.requests import CryptoLatestQuoteRequest

                q = self._source.client.get_crypto_latest_quote(CryptoLatestQuoteRequest(symbol_or_symbols=symbol))[symbol]
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc) from exc
        return Quote(symbol, Decimal(str(q.bid_price)), Decimal(str(q.ask_price)), ensure_utc(q.timestamp))

    def get_positions(self) -> list[Position]:
        """Open positions."""
        try:
            raw = self.client.get_all_positions()
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc) from exc
        return [Position(p.symbol, Decimal(str(p.qty)), Decimal(str(p.avg_entry_price)), Decimal(str(p.market_value))) for p in raw]

    def get_balance(self) -> Balance:
        """Cash and equity from the account."""
        try:
            acct = self.client.get_account()
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc) from exc
        return Balance(Decimal(str(acct.cash)), Decimal(str(acct.equity)))

    def place_order(self, req: OrderRequest) -> Order:
        """Market order (v1: market only, ``day``), idempotent on client id."""
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest

        try:
            existing = self._by_client_id(req.client_order_id)
            if existing is not None:
                return existing
            raw = self.client.submit_order(
                MarketOrderRequest(
                    symbol=req.symbol,
                    qty=float(req.qty),
                    side=OrderSide.BUY if req.side == "buy" else OrderSide.SELL,
                    time_in_force=TimeInForce.DAY if self.market == "equities" else TimeInForce.GTC,
                    client_order_id=req.client_order_id,
                )
            )
        except AdapterError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc) from exc
        return self._to_order(raw)

    def _by_client_id(self, cid: str) -> Order | None:
        try:
            return self._to_order(self.client.get_order_by_client_id(cid))
        except Exception:  # noqa: BLE001
            return None

    def _to_order(self, raw: Any) -> Order:
        status = str(getattr(raw.status, "value", raw.status)).lower()
        mapping = {"new": "new", "accepted": "open", "pending_new": "new", "partially_filled": "partially_filled", "filled": "filled", "canceled": "cancelled", "expired": "expired", "rejected": "rejected"}
        return Order(
            str(raw.id), str(raw.client_order_id), str(raw.symbol), str(getattr(raw.side, "value", raw.side)).lower(),  # type: ignore[arg-type]
            Decimal(str(raw.qty or 0)), Decimal(str(raw.filled_qty or 0)),
            Decimal(str(raw.filled_avg_price)) if raw.filled_avg_price else None,
            mapping.get(status, "open"),  # type: ignore[arg-type]
            ensure_utc(raw.submitted_at), ensure_utc(raw.updated_at or raw.submitted_at),
        )

    def cancel_order(self, order_id: str) -> None:
        """Cancel by id."""
        try:
            self.client.cancel_order_by_id(order_id)
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc) from exc

    def get_order(self, order_id: str) -> Order:
        """Fetch by id."""
        try:
            return self._to_order(self.client.get_order_by_id(order_id))
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc) from exc

    def get_open_orders(self) -> list[Order]:
        """Open orders."""
        from alpaca.trading.enums import QueryOrderStatus
        from alpaca.trading.requests import GetOrdersRequest

        try:
            raw = self.client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN))
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc) from exc
        return [self._to_order(r) for r in raw]

    def market_meta(self, symbol: str) -> MarketMeta:
        """Fractional market orders, $1 minimum notional, zero commission."""
        try:
            asset = self.client.get_asset(symbol)
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc) from exc
        fractional = bool(getattr(asset, "fractionable", False))
        return MarketMeta(symbol=symbol, min_notional=1.0, lot_step=1e-6 if fractional else 1.0, tick_size=0.01, taker_fee=0.0)
