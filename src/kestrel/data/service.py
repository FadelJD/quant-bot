"""DataService: cache-first, incremental, validated access to bars for a universe."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from kestrel.clock import ensure_utc
from kestrel.config import TIMEFRAME_SECONDS, DataConfig
from kestrel.data.cache import Manifest, ParquetCache
from kestrel.data.fetchers import (
    AlpacaSource,
    BarSource,
    CcxtSource,
    FixtureSource,
    SyntheticSource,
    YFinanceSource,
)
from kestrel.data.schema import attach_meta, find_gaps, validate_ohlcv
from kestrel.errors import ConfigError, DataError
from kestrel.logsetup import get_logger

log = get_logger(__name__)


class DataService:
    """Turn ``(market, symbol, timeframe, start, end)`` into a clean cached frame."""

    def __init__(
        self,
        source: BarSource,
        cache: ParquetCache,
        *,
        allow_gaps: bool = False,
        market: str,
    ) -> None:
        """Create a service over one source and one cache."""
        self.source = source
        self.cache = cache
        self.allow_gaps = allow_gaps
        self.market = market
        self.fetch_calls = 0

    @classmethod
    def from_config(
        cls,
        cfg: DataConfig,
        market: str,
        *,
        root: Path | None = None,
        alpaca_key: tuple[str, str] | None = None,
    ) -> DataService:
        """Build a service from config, choosing the source by ``cfg.source``."""
        base = root or Path.cwd()
        cache_dir = cfg.cache_dir if cfg.cache_dir.is_absolute() else base / cfg.cache_dir
        manifest_path = cfg.manifest_path if cfg.manifest_path.is_absolute() else base / cfg.manifest_path
        cache = ParquetCache(cache_dir, Manifest(manifest_path), cfg.max_partition_mb)
        source: BarSource
        if cfg.source == "synthetic":
            source = SyntheticSource(market=market)
        elif cfg.source == "fixtures":
            fixtures = cfg.fixtures_dir or Path("tests/fixtures")
            source = FixtureSource(fixtures if fixtures.is_absolute() else base / fixtures, market)
        elif cfg.source == "ccxt":
            if market != "crypto":
                raise ConfigError("data.source ccxt only serves the crypto market")
            source = CcxtSource(cfg.exchange, rate_per_second=cfg.rate_limit_per_second)
        elif cfg.source == "alpaca":
            if alpaca_key is None:
                raise ConfigError("data.source alpaca needs APCA_API_KEY_ID and APCA_API_SECRET_KEY")
            source = AlpacaSource(market, *alpaca_key)
        elif cfg.source == "yfinance":
            source = YFinanceSource()
        else:  # pragma: no cover - exhaustive by Literal
            raise ConfigError(f"unknown data source {cfg.source}")
        return cls(source, cache, allow_gaps=cfg.allow_gaps, market=market)

    def get_bars(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        *,
        now: datetime | None = None,
    ) -> pd.DataFrame:
        """Return validated bars in ``[start, end]``, fetching only the missing tail.

        Args:
            symbol: Symbol in the source's format.
            timeframe: Bar size.
            start: Window start (UTC).
            end: Window end (UTC, inclusive).
            now: Fetch time for the manifest; defaults to the wall clock.

        Returns:
            A canonical, validated frame.

        Raises:
            DataError: If the source returns nothing for an uncached window, or validation fails.
        """
        s, e = ensure_utc(start), ensure_utc(end)
        step = timedelta(seconds=TIMEFRAME_SECONDS[timeframe])
        cached = self.cache.read(self.market, symbol, timeframe)
        need_head = cached.empty or cached.index[0] > pd.Timestamp(s)
        need_tail = cached.empty or cached.index[-1] + step <= pd.Timestamp(e)
        fetched: list[pd.DataFrame] = []
        if need_head:
            head_end = e if cached.empty else (cached.index[0] - step).to_pydatetime()
            fetched.append(self._fetch(symbol, timeframe, s, head_end))
        if need_tail and not cached.empty:
            tail_start = (cached.index[-1] + step).to_pydatetime()
            fetched.append(self._fetch(symbol, timeframe, tail_start, e))
        if fetched:
            merged = pd.concat([cached, *fetched]) if not cached.empty else pd.concat(fetched)
            merged = merged[~merged.index.duplicated(keep="last")].sort_index()
            if merged.empty:
                raise DataError(f"no bars for {symbol} {timeframe} between {s} and {e}")
            merged = attach_meta(merged, symbol, self.market, timeframe)
            self.cache.write(merged, source=self.source.name, now=now)
            cached = merged
        window = cached[(cached.index >= pd.Timestamp(s)) & (cached.index <= pd.Timestamp(e))]
        if window.empty:
            raise DataError(f"no bars for {symbol} {timeframe} between {s} and {e}")
        return validate_ohlcv(window, timeframe=timeframe, market=self.market, allow_gaps=self.allow_gaps)

    def _fetch(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> pd.DataFrame:
        if end < start:
            return pd.DataFrame()
        self.fetch_calls += 1
        log.info("fetch", symbol=symbol, timeframe=timeframe, start=start.isoformat(), end=end.isoformat())
        frame = self.source.fetch(symbol, timeframe, start, end)
        return frame

    def get_universe_bars(
        self,
        symbols: list[str] | tuple[str, ...],
        timeframe: str,
        start: datetime,
        end: datetime,
        *,
        now: datetime | None = None,
    ) -> dict[str, pd.DataFrame]:
        """Fetch every symbol; a symbol with no data raises ``DataError`` naming it."""
        out: dict[str, pd.DataFrame] = {}
        for symbol in symbols:
            out[symbol] = self.get_bars(symbol, timeframe, start, end, now=now)
        return out

    def check(self) -> list[dict[str, object]]:
        """Validate every cached series and report gaps; used by ``kestrel data check``."""
        rows: list[dict[str, object]] = []
        for market, symbol, timeframe in self.cache.series():
            frame = self.cache.read(market, symbol, timeframe)
            status = "ok"
            detail = ""
            try:
                validate_ohlcv(frame, timeframe=timeframe, market=market, allow_gaps=True)
                gaps = find_gaps(frame.index, timeframe, market)
                if gaps.has_gaps:
                    status = "gaps"
                    detail = f"{gaps.n_gaps} gap(s), largest {gaps.largest_bars} bars, first {gaps.locations[0]}"
            except DataError as exc:
                status = "invalid"
                detail = str(exc)
            rows.append(
                {
                    "market": market,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "rows": int(len(frame)),
                    "first": frame.index[0].isoformat() if len(frame) else None,
                    "last": frame.index[-1].isoformat() if len(frame) else None,
                    "status": status,
                    "detail": detail,
                }
            )
        return rows
