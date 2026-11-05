"""Download 2 years of daily bars for 5 crypto pairs and 10 stocks, trim, and write tests/fixtures/.

Owner runs this once with network access (Alpaca paper key needed for equities):
    uv run python scripts/fetch_fixtures.py
Target: under 2 MB total. Tests never hit the network.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from kestrel.data.fetchers import AlpacaSource, CcxtSource

ROOT = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
CRYPTO = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT"]
STOCKS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "JPM", "XOM", "PG", "KO"]
START, END = datetime(2024, 1, 1, tzinfo=UTC), datetime(2025, 12, 31, tzinfo=UTC)


def main() -> None:
    (ROOT / "crypto").mkdir(parents=True, exist_ok=True)
    src = CcxtSource("binance")
    for s in CRYPTO:
        f = src.fetch(s, "1d", START, END)[["open", "high", "low", "close", "volume"]].astype("float32")
        f.to_parquet(ROOT / "crypto" / f"{s.replace('/', '_')}_1d.parquet")
        print(s, len(f))
    key, sec = os.environ.get("APCA_API_KEY_ID"), os.environ.get("APCA_API_SECRET_KEY")
    if key and sec:
        (ROOT / "equities").mkdir(exist_ok=True)
        a = AlpacaSource("equities", key, sec)
        for s in STOCKS:
            f = a.fetch(s, "1d", START, END)[["open", "high", "low", "close", "volume"]].astype("float32")
            f.to_parquet(ROOT / "equities" / f"{s}_1d.parquet")
            print(s, len(f))
    else:
        print("APCA keys absent: equities fixtures skipped")


if __name__ == "__main__":
    main()
