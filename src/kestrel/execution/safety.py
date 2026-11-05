"""The paper-only safety gate. Non-negotiable: there is no configuration path to a live endpoint."""

from __future__ import annotations

import re
from datetime import datetime

from kestrel.clock import ensure_utc
from kestrel.errors import ConfigError

ALPACA_PAPER_URL = "https://paper-api.alpaca.markets"

ALPACA_LIVE_URLS: tuple[str, ...] = (
    "https://api.alpaca.markets",
    "https://api.alpaca.markets/v2",
    "http://api.alpaca.markets",
)

CCXT_SANDBOX_EXCHANGES: tuple[str, ...] = ("binance", "bybit", "okx")
"""Exchanges whose CCXT class exposes a usable sandbox/testnet. Everything else is rejected."""

KNOWN_LIVE_URLS: tuple[str, ...] = (
    *ALPACA_LIVE_URLS,
    "https://api.binance.com",
    "https://api1.binance.com",
    "https://api.bybit.com",
    "https://www.okx.com",
    "https://api.kraken.com",
    "https://api.coinbase.com",
    "https://api.exchange.coinbase.com",
    "https://api.bitkub.com",
)

_SANDBOX_MARKERS = re.compile(r"(testnet|sandbox|paper|demo)", re.IGNORECASE)


def assert_paper_endpoint(url: str, *, provider: str) -> str:
    """Raise :class:`ConfigError` unless ``url`` is an allowed paper or sandbox endpoint.

    Args:
        url: Base URL the adapter is about to use.
        provider: ``alpaca`` or ``ccxt`` (decides the rule).

    Returns:
        The validated URL.

    Raises:
        ConfigError: For any URL that is not a known paper endpoint. The message is explicit
            about there being no live mode.
    """
    clean = url.strip().rstrip("/")
    if provider == "alpaca":
        if clean != ALPACA_PAPER_URL:
            raise ConfigError(
                f"refusing non-paper Alpaca endpoint {url!r}; only {ALPACA_PAPER_URL} is allowed. "
                "kestrel has no live-money mode."
            )
        return clean
    if provider == "ccxt":
        if any(clean.startswith(live) for live in KNOWN_LIVE_URLS) or not _SANDBOX_MARKERS.search(clean):
            raise ConfigError(
                f"refusing CCXT endpoint {url!r}: it does not look like a testnet or sandbox. "
                "kestrel has no live-money mode."
            )
        return clean
    raise ConfigError(f"unknown provider {provider!r}")


def assert_sandbox_exchange(exchange_id: str) -> str:
    """Reject CCXT exchanges that have no sandbox."""
    if exchange_id not in CCXT_SANDBOX_EXCHANGES:
        raise ConfigError(
            f"exchange {exchange_id!r} has no supported sandbox; allowed: {', '.join(CCXT_SANDBOX_EXCHANGES)}"
        )
    return exchange_id


def client_order_id(strategy: str, symbol: str, bar_ts: datetime, n: int) -> str:
    """Build ``kst-{strategy}-{symbol}-{bar_ts}-{n}`` (symbol slashes become dashes).

    The id is deterministic for a bar so a retried request after a timeout cannot double-fill.
    """
    stamp = ensure_utc(bar_ts).strftime("%Y%m%dT%H%M%S")
    sym = symbol.replace("/", "-").replace(":", "-")
    return f"kst-{strategy}-{sym}-{stamp}-{n}"
