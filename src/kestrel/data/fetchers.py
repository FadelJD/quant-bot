"""Bar sources behind one protocol: CCXT public REST, Alpaca market data, yfinance, fixtures.

Real fetchers are constructed lazily and only when a run needs the network. Tests use
:class:`FixtureSource` and :class:`SyntheticSource`.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

from kestrel.clock import ensure_utc
from kestrel.config import TIMEFRAME_SECONDS
from kestrel.data.ratelimit import TokenBucket, with_backoff
from kestrel.data.schema import attach_meta, empty_ohlcv
from kestrel.data.synthetic import make_synthetic_ohlcv
from kestrel.errors import AdapterError, DataError
from kestrel.logsetup import get_logger

log = get_logger(__name__)


class BarSource(Protocol):
    """Fetch raw bars for one symbol over a half-open window."""

    name: str
    market: str

    def fetch(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> pd.DataFrame:
        """Return bars with open time in ``[start, end]`` as a canonical frame (may be empty)."""
        ...


class SyntheticSource:
    """Deterministic synthetic bars; the seed is derived from the symbol so series differ."""

    name = "synthetic"

    def __init__(self, market: str = "crypto", drift: float = 0.05, vol: float = 0.6) -> None:
        """Create a source with the given drift and volatility."""
        self.market = market
        self.drift = drift
        self.vol = vol
        self.calls = 0

    def fetch(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> pd.DataFrame:
        """Generate bars covering the window."""
        self.calls += 1
        s, e = ensure_utc(start), ensure_utc(end)
        n = int((e - s).total_seconds() // TIMEFRAME_SECONDS[timeframe]) + 1
        seed = sum(ord(c) for c in symbol) * 7919
        frame = make_synthetic_ohlcv(
            seed, self.drift, self.vol, n, start=s, timeframe=timeframe, symbol=symbol, market=self.market
        )
        return frame[(frame.index >= s) & (frame.index <= e)]


class FixtureSource:
    """Reads frozen parquet fixtures from ``tests/fixtures/<market>/<symbol>_<timeframe>.parquet``."""

    name = "fixtures"

    def __init__(self, root: Path, market: str) -> None:
        """Create a fixture source rooted at ``root``."""
        self.root = Path(root)
        self.market = market
        self.calls = 0

    def path_for(self, symbol: str, timeframe: str) -> Path:
        """Fixture path for a series."""
        safe = symbol.replace("/", "_")
        return self.root / self.market / f"{safe}_{timeframe}.parquet"

    def fetch(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> pd.DataFrame:
        """Read the fixture and slice it to the window."""
        self.calls += 1
        path = self.path_for(symbol, timeframe)
        if not path.exists():
            raise DataError(f"fixture not found for {symbol} {timeframe}: {path}")
        frame = pd.read_parquet(path)
        frame.index = pd.DatetimeIndex(frame.index).tz_convert("UTC")
        frame.index.name = "ts"
        s, e = ensure_utc(start), ensure_utc(end)
        out = frame[(frame.index >= s) & (frame.index <= e)]
        return attach_meta(out, symbol, self.market, timeframe)


class CcxtSource:
    """Public OHLCV history through CCXT; no key needed. Paginates ``fetch_ohlcv``."""

    name = "ccxt"
    market = "crypto"

    def __init__(
        self,
        exchange_id: str = "binance",
        *,
        rate_per_second: float = 5.0,
        sleep: Callable[[float], None] | None = None,
        exchange: Any | None = None,
        page_limit: int = 1000,
    ) -> None:
        """Create a source for ``exchange_id``. ``exchange`` can be injected for tests."""
        self.exchange_id = exchange_id
        self.page_limit = page_limit
        self._sleep = sleep
        self.bucket = TokenBucket(rate=rate_per_second, capacity=rate_per_second, **({"sleep": sleep} if sleep else {}))
        self._exchange = exchange
        self.name = f"ccxt:{exchange_id}"

    @property
    def exchange(self) -> Any:
        """The CCXT exchange instance (constructed on first use)."""
        if self._exchange is None:
            import ccxt

            if not hasattr(ccxt, self.exchange_id):
                raise DataError(f"unknown CCXT exchange {self.exchange_id!r}")
            self._exchange = getattr(ccxt, self.exchange_id)({"enableRateLimit": True})
        return self._exchange

    @staticmethod
    def _is_rate_limited(exc: BaseException) -> bool:
        name = type(exc).__name__
        return name in {"RateLimitExceeded", "DDoSProtection"} or "429" in str(exc)

    def fetch(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> pd.DataFrame:
        """Page through ``fetch_ohlcv`` from ``start`` until ``end``."""
        s, e = ensure_utc(start), ensure_utc(end)
        since = int(s.timestamp() * 1000)
        end_ms = int(e.timestamp() * 1000)
        step_ms = TIMEFRAME_SECONDS[timeframe] * 1000
        rows: list[list[float]] = []
        try:
            while since <= end_ms:
                self.bucket.acquire()
                page = with_backoff(
                    lambda: self.exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=self.page_limit),
                    is_rate_limited=self._is_rate_limited,
                    **({"sleep": self._sleep} if self._sleep else {}),
                )
                assert isinstance(page, list)
                if not page:
                    break
                rows.extend(page)
                last = int(page[-1][0])
                if last + step_ms <= since:
                    break
                since = last + step_ms
                if len(page) < self.page_limit:
                    break
        except DataError:
            raise
        except Exception as exc:  # noqa: BLE001 - CCXT raises a wide family; translate at the edge
            msg = str(exc)
            if "restricted location" in msg.lower() or "451" in msg or "403" in msg:
                raise AdapterError(f"provider {self.exchange_id} blocked from this region: {msg}") from exc
            raise DataError(f"ccxt fetch failed for {symbol} {timeframe}: {msg}") from exc
        if not rows:
            return empty_ohlcv(symbol, self.market, timeframe)
        frame = pd.DataFrame(rows, columns=["ms", "open", "high", "low", "close", "volume"])
        frame["ts"] = pd.to_datetime(frame["ms"], unit="ms", utc=True)
        frame = frame.drop(columns="ms").set_index("ts")
        frame = frame[(frame.index >= s) & (frame.index <= e)]
        return attach_meta(frame, symbol, self.market, timeframe)


class AlpacaSource:
    """Daily and intraday bars from Alpaca Market Data (free tier, IEX feed). Needs a paper key."""

    name = "alpaca"

    def __init__(self, market: str, key_id: str, secret: str, *, client: Any | None = None) -> None:
        """Create a source; ``client`` can be injected for tests."""
        self.market = market
        self._key_id = key_id
        self._secret = secret
        self._client = client

    @property
    def client(self) -> Any:
        """The historical data client (constructed on first use)."""
        if self._client is None:
            if self.market == "equities":
                from alpaca.data.historical import StockHistoricalDataClient

                self._client = StockHistoricalDataClient(self._key_id, self._secret)
            else:
                from alpaca.data.historical import CryptoHistoricalDataClient

                self._client = CryptoHistoricalDataClient(self._key_id, self._secret)
        return self._client

    def fetch(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> pd.DataFrame:
        """Request bars and convert to the canonical frame."""
        from alpaca.data.requests import CryptoBarsRequest, StockBarsRequest
        from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

        unit_map = {
            "1m": TimeFrame(1, TimeFrameUnit.Minute),
            "5m": TimeFrame(5, TimeFrameUnit.Minute),
            "15m": TimeFrame(15, TimeFrameUnit.Minute),
            "1h": TimeFrame(1, TimeFrameUnit.Hour),
            "4h": TimeFrame(4, TimeFrameUnit.Hour),
            "1d": TimeFrame(1, TimeFrameUnit.Day),
        }
        s, e = ensure_utc(start), ensure_utc(end)
        try:
            if self.market == "equities":
                req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=unit_map[timeframe], start=s, end=e, feed="iex")
                bars = self.client.get_stock_bars(req)
            else:
                req = CryptoBarsRequest(symbol_or_symbols=symbol, timeframe=unit_map[timeframe], start=s, end=e)
                bars = self.client.get_crypto_bars(req)
        except Exception as exc:  # noqa: BLE001
            raise DataError(f"alpaca fetch failed for {symbol} {timeframe}: {exc}") from exc
        df = bars.df
        if df.empty:
            return empty_ohlcv(symbol, self.market, timeframe)
        if isinstance(df.index, pd.MultiIndex):
            df = df.xs(symbol, level="symbol")
        df = df[["open", "high", "low", "close", "volume"]].copy()
        df.index = pd.DatetimeIndex(df.index).tz_convert("UTC")
        df.index.name = "ts"
        if timeframe == "1d":
            df.index = df.index.normalize()
        return attach_meta(df, symbol, self.market, timeframe)


class YFinanceSource:
    """Research-only fallback for US equities. Never used for live decisions."""

    name = "yfinance"
    market = "equities"

    def __init__(self, *, download: Callable[..., pd.DataFrame] | None = None) -> None:
        """Create a source; ``download`` can be injected for tests."""
        self._download = download

    def fetch(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> pd.DataFrame:
        """Download daily bars via ``yfinance``."""
        if timeframe != "1d":
            raise DataError("yfinance source supports daily bars only")
        if self._download is None:
            import yfinance as yf

            self._download = yf.download
        s, e = ensure_utc(start), ensure_utc(end)
        log.warning("yfinance_research_only", symbol=symbol)
        df = self._download(symbol, start=s.date(), end=e.date(), auto_adjust=False, progress=False)
        if df is None or df.empty:
            return empty_ohlcv(symbol, self.market, timeframe)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
        idx = pd.DatetimeIndex(df.index)
        df.index = (idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC"))
        df.index.name = "ts"
        return attach_meta(df, symbol, self.market, timeframe)


def utcnow() -> datetime:
    """Current UTC time (kept here so fetchers can be patched in tests)."""
    return datetime.now(tz=UTC)
