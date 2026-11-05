"""CCXT adapter, sandbox only. ``set_sandbox_mode(True)`` is called and the URL is verified."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

import pandas as pd

from kestrel.clock import ensure_utc
from kestrel.data.calendar import CryptoCalendar
from kestrel.data.fetchers import CcxtSource
from kestrel.errors import AdapterError, ConfigError
from kestrel.execution.protocol import Balance, Order, OrderRequest, Position, Quote
from kestrel.execution.safety import assert_paper_endpoint, assert_sandbox_exchange
from kestrel.types import MarketMeta


class CcxtAdapter:
    """Crypto paper trading on an exchange testnet through CCXT."""

    market: Literal["crypto", "equities"] = "crypto"

    def __init__(self, exchange_id: str, api_key: str, secret: str, *, exchange: Any | None = None, quote_currency: str = "USDT") -> None:
        """Create the adapter and verify the sandbox before any network call.

        Args:
            exchange_id: ``binance``, ``bybit`` or ``okx``.
            api_key: Testnet API key (from the environment only).
            secret: Testnet secret.
            exchange: Injected CCXT-like object for tests.
            quote_currency: Currency used for cash and equity.

        Raises:
            ConfigError: If the exchange has no sandbox or the resulting URL is not a testnet.
        """
        assert_sandbox_exchange(exchange_id)
        self.exchange_id = exchange_id
        self.name = f"ccxt:{exchange_id}:sandbox"
        self.quote_currency = quote_currency
        if exchange is None:
            import ccxt

            exchange = getattr(ccxt, exchange_id)({"apiKey": api_key, "secret": secret, "enableRateLimit": True})
        exchange.set_sandbox_mode(True)
        urls = exchange.urls.get("api", {})
        url = urls if isinstance(urls, str) else str(urls.get("public") or urls.get("private") or next(iter(urls.values()), ""))
        assert_paper_endpoint(url, provider="ccxt")
        self.exchange = exchange
        self.calendar = CryptoCalendar()
        self._markets: dict[str, Any] | None = None
        self._source = CcxtSource(exchange_id, exchange=exchange)

    def _markets_loaded(self) -> dict[str, Any]:
        if self._markets is None:
            try:
                self._markets = self.exchange.load_markets()
            except Exception as exc:  # noqa: BLE001
                raise self._translate(exc) from exc
        return self._markets

    @staticmethod
    def _translate(exc: BaseException) -> AdapterError:
        msg = str(exc)
        if "restricted location" in msg.lower() or "451" in msg:
            return AdapterError("provider blocked from this region: " + msg)
        return AdapterError(msg)

    def is_open(self, ts: datetime) -> bool:
        """Crypto is always open."""
        return True

    def next_open(self, ts: datetime) -> datetime:
        """Next bar boundary."""
        return self.calendar.next_open(ts)

    def get_bars(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> pd.DataFrame:
        """Public OHLCV through the data fetcher."""
        return self._source.fetch(symbol, timeframe, start, end)

    def get_quote(self, symbol: str) -> Quote:
        """Best bid/ask from the ticker."""
        try:
            t = self.exchange.fetch_ticker(symbol)
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc) from exc
        ts = datetime.fromtimestamp(t["timestamp"] / 1000, tz=ensure_utc(datetime.now().astimezone()).tzinfo) if t.get("timestamp") else datetime.now().astimezone()
        return Quote(symbol, Decimal(str(t["bid"])), Decimal(str(t["ask"])), ensure_utc(ts))

    def get_positions(self) -> list[Position]:
        """Spot balances other than the quote currency, valued at the last price."""
        try:
            bal = self.exchange.fetch_balance()
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc) from exc
        out = []
        for cur, amount in bal.get("total", {}).items():
            if cur == self.quote_currency or not amount:
                continue
            symbol = f"{cur}/{self.quote_currency}"
            if symbol not in self._markets_loaded():
                continue
            px = Decimal(str(self.exchange.fetch_ticker(symbol)["last"]))
            q = Decimal(str(amount))
            out.append(Position(symbol, q, Decimal(0), q * px))
        return out

    def get_balance(self) -> Balance:
        """Quote-currency cash plus marked positions."""
        try:
            bal = self.exchange.fetch_balance()
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc) from exc
        cash = Decimal(str(bal.get("free", {}).get(self.quote_currency, 0) or 0))
        mv = sum((p.market_value for p in self.get_positions()), Decimal(0))
        return Balance(cash, cash + mv, self.quote_currency)

    def place_order(self, req: OrderRequest) -> Order:
        """Market or limit order with a client id for idempotency."""
        params = {"clientOrderId": req.client_order_id, "newClientOrderId": req.client_order_id}
        try:
            existing = self._find_by_client_id(req.client_order_id, req.symbol)
            if existing is not None:
                return existing
            raw = self.exchange.create_order(
                req.symbol, req.order_type, req.side, float(req.qty), float(req.limit_price) if req.limit_price else None, params
            )
        except AdapterError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc) from exc
        return self._to_order(raw)

    def _find_by_client_id(self, cid: str, symbol: str) -> Order | None:
        try:
            for raw in self.exchange.fetch_open_orders(symbol):
                if raw.get("clientOrderId") == cid:
                    return self._to_order(raw)
        except Exception:  # noqa: BLE001 - best effort; a miss just means a normal submit
            return None
        return None

    def _to_order(self, raw: dict[str, Any]) -> Order:
        status_map = {"open": "open", "closed": "filled", "canceled": "cancelled", "cancelled": "cancelled", "rejected": "rejected", "expired": "expired"}
        status = status_map.get(str(raw.get("status")), "open")
        filled = Decimal(str(raw.get("filled") or 0))
        amount = Decimal(str(raw.get("amount") or 0))
        if status == "open" and 0 < filled < amount:
            status = "partially_filled"
        ts = datetime.fromtimestamp((raw.get("timestamp") or 0) / 1000, tz=ensure_utc(datetime.now().astimezone()).tzinfo)
        fee = Decimal(str((raw.get("fee") or {}).get("cost") or 0))
        return Order(
            str(raw["id"]), str(raw.get("clientOrderId") or ""), str(raw["symbol"]), raw["side"], amount, filled,
            Decimal(str(raw["average"])) if raw.get("average") else None, status, ensure_utc(ts), ensure_utc(ts), fee,  # type: ignore[arg-type]
        )

    def cancel_order(self, order_id: str) -> None:
        """Cancel by exchange id (symbol looked up from open orders)."""
        try:
            for raw in self.exchange.fetch_open_orders():
                if str(raw["id"]) == order_id:
                    self.exchange.cancel_order(order_id, raw["symbol"])
                    return
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc) from exc

    def get_order(self, order_id: str) -> Order:
        """Fetch one order."""
        try:
            return self._to_order(self.exchange.fetch_order(order_id))
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc) from exc

    def get_open_orders(self) -> list[Order]:
        """All open orders."""
        try:
            return [self._to_order(r) for r in self.exchange.fetch_open_orders()]
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc) from exc

    def market_meta(self, symbol: str) -> MarketMeta:
        """Limits from ``load_markets``."""
        m = self._markets_loaded().get(symbol)
        if m is None:
            raise ConfigError(f"symbol {symbol!r} not listed on {self.exchange_id} sandbox")
        limits = m.get("limits", {})
        precision = m.get("precision", {})
        step = precision.get("amount")
        lot = float(step) if step and step < 1 else (10 ** -int(step) if step else 1e-6)
        return MarketMeta(
            symbol=symbol,
            min_notional=float((limits.get("cost") or {}).get("min") or 10.0),
            lot_step=lot,
            tick_size=float(precision.get("price") or 0.01),
            taker_fee=float(m.get("taker") or 0.001),
        )
