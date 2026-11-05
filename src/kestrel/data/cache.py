"""Parquet cache with a manifest: ``data/cache/{market}/{symbol}/{timeframe}.parquet``.

Files above ``max_partition_mb`` are split by year into ``{timeframe}/{year}.parquet``. The
manifest records source, fetch time, and row counts so every run is reproducible.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from kestrel.data.schema import META_COLUMNS, OHLCV_COLUMNS, empty_ohlcv


def _safe(symbol: str) -> str:
    return symbol.replace("/", "_").replace(":", "_")


@dataclass
class ManifestEntry:
    """One cached file's provenance."""

    market: str
    symbol: str
    timeframe: str
    source: str
    fetched_at: str
    rows: int
    first_ts: str | None
    last_ts: str | None
    path: str


class Manifest:
    """JSON manifest of every cached file, keyed by ``market/symbol/timeframe``."""

    def __init__(self, path: Path) -> None:
        """Load the manifest at ``path`` if it exists."""
        self.path = path
        self.entries: dict[str, ManifestEntry] = {}
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            for key, val in raw.get("entries", {}).items():
                self.entries[key] = ManifestEntry(**val)

    @staticmethod
    def key(market: str, symbol: str, timeframe: str) -> str:
        """Manifest key for a series."""
        return f"{market}/{symbol}/{timeframe}"

    def record(self, entry: ManifestEntry) -> None:
        """Insert or replace an entry and write the file."""
        self.entries[self.key(entry.market, entry.symbol, entry.timeframe)] = entry
        self.save()

    def save(self) -> None:
        """Write the manifest as pretty JSON with stable key order."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "entries": {k: asdict(v) for k, v in sorted(self.entries.items())},
        }
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


class ParquetCache:
    """Read and write canonical OHLCV frames as parquet."""

    def __init__(self, root: Path, manifest: Manifest, max_partition_mb: int = 50) -> None:
        """Create a cache rooted at ``root``."""
        self.root = Path(root)
        self.manifest = manifest
        self.max_partition_bytes = max_partition_mb * 1024 * 1024

    def dir_for(self, market: str, symbol: str) -> Path:
        """Directory holding one symbol's files."""
        return self.root / market / _safe(symbol)

    def _single_path(self, market: str, symbol: str, timeframe: str) -> Path:
        return self.dir_for(market, symbol) / f"{timeframe}.parquet"

    def _partition_dir(self, market: str, symbol: str, timeframe: str) -> Path:
        return self.dir_for(market, symbol) / timeframe

    def read(self, market: str, symbol: str, timeframe: str) -> pd.DataFrame:
        """Read the cached frame for a series, or an empty canonical frame if none."""
        single = self._single_path(market, symbol, timeframe)
        parts = self._partition_dir(market, symbol, timeframe)
        frames: list[pd.DataFrame] = []
        if single.exists():
            frames.append(pd.read_parquet(single))
        if parts.is_dir():
            for p in sorted(parts.glob("*.parquet")):
                frames.append(pd.read_parquet(p))
        if not frames:
            return empty_ohlcv(symbol, market, timeframe)
        out = pd.concat(frames)
        out = out[~out.index.duplicated(keep="last")].sort_index()
        out.index = pd.DatetimeIndex(out.index).tz_convert("UTC")
        out.index.name = "ts"
        return out

    def write(self, frame: pd.DataFrame, *, source: str, now: datetime | None = None) -> Path:
        """Write a canonical frame, partitioning by year if it exceeds the size cap.

        Args:
            frame: Canonical OHLCV frame with ``symbol``, ``market`` and ``timeframe`` columns.
            source: Name of the fetcher that produced it.
            now: Fetch time (UTC); defaults to the wall clock.

        Returns:
            The file or directory written.
        """
        if frame.empty:
            raise ValueError("refusing to write an empty frame")
        market = str(frame["market"].iloc[0])
        symbol = str(frame["symbol"].iloc[0])
        timeframe = str(frame["timeframe"].iloc[0])
        cols = [*OHLCV_COLUMNS, *META_COLUMNS]
        out = frame[cols].sort_index()
        single = self._single_path(market, symbol, timeframe)
        parts = self._partition_dir(market, symbol, timeframe)
        single.parent.mkdir(parents=True, exist_ok=True)
        out.to_parquet(single, index=True)
        written: Path = single
        if single.stat().st_size > self.max_partition_bytes:
            single.unlink()
            parts.mkdir(parents=True, exist_ok=True)
            for year, chunk in out.groupby(out.index.year):
                chunk.to_parquet(parts / f"{year}.parquet", index=True)
            written = parts
        elif parts.is_dir():
            for p in parts.glob("*.parquet"):
                p.unlink()
            parts.rmdir()
        stamp = (now or datetime.now(tz=UTC)).isoformat()
        self.manifest.record(
            ManifestEntry(
                market=market,
                symbol=symbol,
                timeframe=timeframe,
                source=source,
                fetched_at=stamp,
                rows=int(len(out)),
                first_ts=out.index[0].isoformat(),
                last_ts=out.index[-1].isoformat(),
                path=str(written.relative_to(self.root)),
            )
        )
        return written

    def size_bytes(self) -> int:
        """Total bytes of parquet under the cache root."""
        if not self.root.exists():
            return 0
        return sum(p.stat().st_size for p in self.root.rglob("*.parquet"))

    def series(self) -> list[tuple[str, str, str]]:
        """List ``(market, symbol, timeframe)`` for every cached series."""
        return [(e.market, e.symbol, e.timeframe) for e in self.manifest.entries.values()]
