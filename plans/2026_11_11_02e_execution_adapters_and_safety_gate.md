# 02e · Execution adapters and the paper-only safety gate

Created 2026-11-11 · Wave 2 · Parallel with 02a to 02d, 02f, 02g · Needs 01 · Spec section 12

## Goal

One protocol, three implementations, and a safety gate that makes a live endpoint unreachable by
any configuration. This lane holds the project's most important non-negotiable rule.

## Owns

`src/kestrel/execution/`.

## Current state

Protocol, value types, `safety.py`, `MockAdapter`, `CcxtAdapter`, `AlpacaAdapter` and a Bitkub stub
exist. Only the mock has ever been constructed. Defects D11, D22 (adapter half).

## Work items

1. **Safety gate, fail closed.**
   - `AlpacaAdapter`: base URL must equal `https://paper-api.alpaca.markets` exactly. Checked
     before the SDK client is constructed. Pass `paper=True` and never accept a URL from config.
   - `CcxtAdapter`: exchange id must be in the sandbox allowlist (`binance`, `bybit`, `okx`);
     `set_sandbox_mode(True)` is called; then **every** URL in `exchange.urls["api"]` (it is a
     nested dict on most exchanges) is walked and each must match a testnet marker and must not
     match any known live host. One bad URL raises `ConfigError`.
   - OKX has no separate host: its demo mode is a header (`x-simulated-trading: 1`). Verify how
     CCXT expresses it and gate on that header being set, or drop OKX from the allowlist and say so.
   - Re-check after `load_markets`, because CCXT can rewrite URLs.
   - `KNOWN_LIVE_URLS` is the list wave 5 iterates over; make it complete for Alpaca, Binance
     (including `api1` to `api4`, `fapi`, `dapi`), Bybit, OKX, Kraken, Coinbase, Bitkub.
   - No `--live` flag, no env var, no config field. Add a module docstring saying so.
2. **Decimal boundary (D22).** `OrderRequest`, `Order`, `Position`, `Balance`, `Quote` carry
   `Decimal`. Provide `to_decimal(float, step)` that quantises to the lot step, and convert exactly
   once on the way in and once on the way out. No float arithmetic on money inside `execution/`.
3. **Idempotency.** `client_order_id` is `kst-{strategy}-{symbol}-{bar_ts}-{n}`. Check each
   venue's length and character limits (Binance 36 characters, Alpaca 128, Bybit 36) and shorten
   deterministically when needed (hash suffix), keeping the `kst-` prefix. `place_order` with a
   known id returns the existing order: look up open **and** recently closed orders.
4. **`MockAdapter`.** Deterministic and scriptable. Scenario fields: reject by symbol or every
   nth, partial fill fraction, timeout (order stays open until `settle_open`), stale quote,
   scripted failure per method, fee rate. Add: latency in simulated seconds, a `drift()` helper
   that changes a broker-side position, and loading scenarios from YAML. Prices come from an
   injected feed; provide `BarPriceFeed(frames)` that returns the last close at or before `now`
   in O(log n) (prepares the D25 fix).
5. **`CcxtAdapter`.**
   - Fix `get_quote` (D11): build the timestamp with `datetime.fromtimestamp(ms / 1000, tz=UTC)`.
   - Positions on spot are balances. Average cost is unknown from the venue: report `Decimal(0)`
     and document that the local state store carries cost basis.
   - `market_meta`: CCXT precision can be decimal places or tick size depending on
     `exchange.precisionMode`. Handle both.
   - Translate errors: region block (`errors.raise_if_region_blocked` from plan 01), insufficient funds,
     invalid order, network timeout. All become `AdapterError` with a readable message.
   - Testnet balances reset or refill. Document how per exchange (handoff note for 04c).
6. **`AlpacaAdapter`.**
   - Verify every call against the current `alpaca-py` API: `TradingClient`, `MarketOrderRequest`,
     `GetOrdersRequest`, `get_order_by_client_id`, enum values, field names on `Order`,
     `Position`, `TradeAccount`. Record the doc URLs and date.
   - Equities: market orders only, time in force `day`, fractional quantities for market orders,
     never submit when `is_open(now)` is false (raise `AdapterError("market closed")`).
   - Crypto via Alpaca uses `gtc` and symbols like `BTC/USD`.
   - Pattern-day-trader rejections surface as a clear `AdapterError`.
7. **Bitkub stub.** Keep `NotImplementedError` in the constructor with the documented interface.
8. **Contract test harness, for the owner's machine.** `scripts/contract_check.py`: when
   `KESTREL_INTEGRATION=1` and keys are present, run read-only calls plus one tiny order that is
   cancelled, against the paper endpoint. Prints pass or fail per call. The agent never runs it;
   wave 5 wraps it as the `contract` marker.
9. **Adapter factory.** `build_adapter(cfg, secrets, clock)` in `execution/factory.py`, returning
   the right adapter and raising a readable `ConfigError` when keys are missing. 04a calls it.

## Done when

- Constructing either real adapter with any URL from `KNOWN_LIVE_URLS` raises `ConfigError` before
  a network call (checked with a fake exchange object from a scratch script).
- `MockAdapter` runs every scenario type.
- No float money arithmetic remains in `execution/`.
- D11 closed; D22 adapter half closed. Provider facts recorded with URL and date.

## Out of scope

Running against real paper endpoints. Limit orders beyond the protocol field. Tests.
