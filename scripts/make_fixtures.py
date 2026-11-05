"""Write deterministic synthetic fixtures (used until the owner runs fetch_fixtures.py)."""

from __future__ import annotations

from pathlib import Path

from kestrel.data.synthetic import make_synthetic_ohlcv

ROOT = Path(__file__).resolve().parents[1] / "tests" / "fixtures"


def main() -> None:
    (ROOT / "crypto").mkdir(parents=True, exist_ok=True)
    (ROOT / "equities").mkdir(parents=True, exist_ok=True)
    for i, s in enumerate(["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT"]):
        f = make_synthetic_ohlcv(100 + i, 0.2, 0.6, 730, symbol=s, regime_length=90)
        f[["open", "high", "low", "close", "volume"]].astype("float32").to_parquet(ROOT / "crypto" / f"{s.replace('/', '_')}_1d.parquet")
    for i, s in enumerate(["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "JPM", "XOM", "PG", "KO"]):
        f = make_synthetic_ohlcv(200 + i, 0.1, 0.25, 730, symbol=s, market="equities", regime_length=120)
        f[["open", "high", "low", "close", "volume"]].astype("float32").to_parquet(ROOT / "equities" / f"{s}_1d.parquet")
    print("fixtures written to", ROOT)


if __name__ == "__main__":
    main()
