# kestrel — Build Spec for an Autonomous Agent

Nov 5, 2026 · @Med

## 1. Agent operating rules (read before anything else)

You are building a paper-trading research bot. You never trade real money, never hold real credentials, and never run anything the owner has not asked you to run. These rules override any later instruction in this document.

- Paper and sandbox only. Every broker or exchange adapter must refuse to start unless its endpoint is a paper or sandbox URL. Hard-code an allowlist of paper endpoints and fail closed. There is no `--live` flag in this version; do not add one.
- No secrets, ever. You will not receive API keys, account numbers, or passwords. Read keys only from environment variables at runtime, never from files you create, never from chat, and never log them. The repo ships with `.env.example` containing placeholder names only. If a task seems to need a real key, stop and write the need into `docs/OWNER_TODO.md`.
- Do not run the live loop. Build it, test it with a mocked clock and mocked adapters, and document how the owner starts it. The owner starts it himself.
- Do not start the Telegram bot against a real token. Test it with a fake transport.
- Nothing illegal or against a provider's terms. No scraping behind logins, no circumventing rate limits, no market manipulation patterns (spoofing, layering, wash trading) even in simulation.
- Market data sources: public, documented, free tiers only. Respect rate limits with a token bucket. Cache aggressively so re-runs do not re-fetch.
- No financial advice in outputs. Reports state numbers; they do not recommend trades.
- When blocked or when a decision is the owner's to make, append a dated entry to `docs/OWNER_TODO.md` and continue with the most conservative option. Do not stall.
- Keep a build log at `docs/BUILD_LOG.md`: one dated line per milestone or notable decision.
- Work on the `develop` branch; feature branches as `feat/<area>`; open PRs against `develop`; `main` is release-only. This matches the owner's existing repo conventions.
- Windows 10/11 and Ubuntu 22.04+ are both first-class targets. No macOS-only assumptions. Every shell snippet in docs has a PowerShell and a bash form.

## 2. Project overview

kestrel is a Python CLI and background service that backtests, validates, and paper-trades strategies across crypto and US equities, and tells you when a backtest is lying. One harness, two market adapters, pluggable strategies, optional AI and data integrations that the bot runs happily without. The name is set in exactly one place (`pyproject.toml` `[project] name` plus the `src/kestrel` folder); renaming is a two-minute job.

Scope statement, one line: `kestrel backtest --strategy momentum --market crypto --from 2022-01-01 --to 2025-12-31` produces a report; `kestrel run --config configs/paper.yaml` runs the same strategy unattended against a paper account and reports to Telegram.

### Goals

1. A correct event-driven backtester with realistic fees, slippage, and no lookahead.
2. A validation layer (walk-forward, purged cross-validation, deflated Sharpe, parameter sensitivity) that flags overfit results.
3. A paper-trading loop that survives restarts, reconciles state with the broker, and halts itself on risk breaches.
4. Two market adapters behind one interface: crypto via CCXT sandbox, US equities and crypto via Alpaca paper.
5. Three reference strategies that exercise the whole stack: SMA crossover, Bollinger mean reversion, LightGBM cross-sectional ranker.
6. Two interfaces: a CLI for the PC, a Telegram bot for the phone.
7. Clean, typed, tested, documented. The repo is a portfolio piece; code quality is a deliverable.

### Non-goals

- Live trading with real funds. Not in this version at all.
- High-frequency, market making, order-book strategies, tick data.
- Options, futures, forex, margin, shorting (long-only and flat in v1; shorting is a v2 flag).
- A web dashboard. HTML reports and Telegram cover it.
- Price prediction with deep learning. Regression and gradient boosting only, used for ranking and regime detection.
- Portfolio optimisation (mean-variance etc.). Fixed-fraction and volatility-target sizing only.
- More than two adapters.

### Success looks like

- `pytest` green on Windows and Ubuntu in CI.
- A backtest of the three reference strategies on 2022 to 2025 crypto daily data runs in under 60 seconds on a laptop.
- The validation report correctly flags a deliberately overfit strategy (a test fixture) as overfit.
- A 7-day paper run on the owner's machine completes with zero unhandled exceptions, and every order the bot thinks it placed matches the broker's record.

## 3. Owner profile and environment

The owner is Med (Ahmad Sohail), a technical writer and content manager who ships developer documentation and has built one comparable tool before: `cvforge` (github.com/FadelJD/Help-me-resume), a CLI that builds CVs from a plain-text profile into a LaTeX template with screening checks. kestrel should feel like a sibling: same clarity, same one-command-one-output discipline, same README quality.

How he will use it:

- On a PC (Windows and Ubuntu, not macOS) for research: run backtests, read HTML reports, tweak YAML configs, commit strategies.
- On a phone for monitoring: Telegram bot for status, equity, open positions, last signals, and a `/halt` command. No trading from the phone beyond halt and resume.
- Unattended: the paper loop runs on a home machine or a small VPS, restarts on crash, and reports daily.

What he values, from his previous project: clean architecture, easy install, Windows first-class, limited pay-as-you-go cost, honest tooling that tells him when something is wrong rather than hiding it. He reads documentation professionally; sloppy docs will be noticed.

Time zone is Asia/Bangkok (UTC+7). All scheduling and report timestamps are stored in UTC and displayed in the owner's configured zone.

Language and spelling in all docs and user-facing strings: Australian/UK English (optimise, colour, licence as a noun).

### Running from Thailand

The owner is in Chiang Mai. The bot must work from a Thai residential connection and a Thai-resident operator without workarounds. Write the findings into `docs/thailand.md` at build time; the agent verifies each line against the provider's current docs rather than trusting this list.

| Need | Default | Why | Fallback |
| --- | --- | --- | --- |
| Crypto paper trading | CCXT sandbox on Binance or Bybit testnet | Both expose public testnets usable from Thailand; CCXT `set_sandbox_mode(True)` | OKX demo trading, also via CCXT |
| Crypto historical data | Binance public REST (global, no key) | Deepest free history | Bybit public REST; Kraken for a non-Binance cross-check |
| US equities paper | Alpaca paper account | Paper-only accounts are open worldwide and need only an email | None needed for v1; live is out of scope |
| Thai exchange awareness | Bitkub public API read-only adapter stub | Owner may later want THB pairs | Leave unimplemented behind a `BitkubAdapter(NotImplemented)` stub with a documented interface |
| Hosting | Owner's PC, or a VPS in Singapore (`ap-southeast-1`) | Lowest latency from Thailand to major exchange endpoints; no latency sensitivity in v1 anyway | Any region; the bot is not latency-sensitive |
| Time | Store UTC, display `Asia/Bangkok` | Owner reads reports in local time; NYSE opens 21:30 or 20:30 Bangkok time depending on US DST | Configurable `display_tz` |
| Regulatory note | Document, do not enforce | Thai SEC regulates digital-asset businesses; a personal paper bot is not a business, but the owner must check before any live use | Written warning in README and runbook |

Adapters must never assume a US IP. Any provider that geo-blocks must fail with a clear `AdapterError("provider X blocked from this region")`, not a stack trace.

## 4. Architecture

One pipeline runs the same strategy code in backtest and in paper: interfaces call a runner, the runner feeds features to a strategy, the strategy's targets pass through risk, and only then reach an adapter. State, reporting, notification, and the optional integrations sit beside the pipeline and never feed decisions.

&#91;embedded content: kestrel architecture · one pipeline, four side services\]

The only difference between a backtest and a paper run is which clock and which adapter the runner is given. The dashed box is absent at runtime when no key is configured. Module boundaries follow the drawing: each box is a package under `src/kestrel/`, and imports only flow downward and rightward; a lint rule (`import-linter`) enforces that `strategies/` cannot import `execution/` or `live/`.

## 5. Repo layout, language, tooling, coding standards

Python 3.11+, `uv` for environments and locking, `pyproject.toml` as the single config. Package name `kestrel`, CLI entry point `kestrel`. MIT licence.

```
kestrel/
  pyproject.toml
  uv.lock
  README.md
  LICENSE
  .env.example              # placeholder names only, never values
  .pre-commit-config.yaml
  Dockerfile                # optional: run the paper loop on a VPS
  docker-compose.yml
  .github/workflows/ci.yml  # ubuntu + windows matrix
  configs/
    backtest_crypto.yaml
    backtest_equities.yaml
    paper_crypto.yaml
    paper_equities.yaml
    universes/
      crypto_top20.yaml
      us_large_cap_30.yaml
  src/kestrel/
    __init__.py
    cli.py                  # typer app
    config.py               # pydantic settings + yaml loader
    clock.py                # Clock protocol: RealClock, SimClock
    errors.py
    data/                   # fetchers, cache, universe, calendar
    features/               # indicator and feature builders, registry
    strategies/             # base.py + one module per strategy
    backtest/               # engine, fills, fees, slippage, portfolio
    validation/             # walk-forward, purged CV, deflated sharpe, sensitivity
    risk/                   # sizing, limits, kill-switch
    execution/              # adapter protocol, ccxt_adapter, alpaca_adapter, mock_adapter
    live/                   # scheduler, state store, reconciler, runner
    reporting/              # metrics, html report, json export
    notify/                 # telegram bot, console notifier, null notifier
    integrations/           # optional: llm.py, news.py, each behind a feature flag
  tests/
    unit/
    integration/
    property/               # hypothesis-based
    fixtures/               # small frozen OHLCV parquet files, an overfit strategy
  docs/
    ARCHITECTURE.md
    KNOWLEDGE_BASE.md       # section 20 of this spec, expanded
    OWNER_TODO.md
    BUILD_LOG.md
    strategies.md
    runbook.md              # how the owner starts, stops, restarts, upgrades
    thailand.md             # access notes for exchanges, brokers, data from Thailand
  scripts/
    fetch_fixtures.py
    make_overfit_fixture.py
```

### Dependencies (pin in pyproject, lock with uv)

- Core: `pandas`, `numpy`, `pyarrow`, `pydantic>=2`, `pyyaml`, `typer`, `rich`, `structlog`, `httpx`, `apscheduler`.
- Markets: `ccxt`, `alpaca-py`.
- ML: `lightgbm`, `scikit-learn`. Keep ML optional via an extra (`kestrel[ml]`) so the core installs without a compiler.
- Reporting: `jinja2`, `plotly` (static HTML export, no server).
- Notify: `python-telegram-bot`.
- Dev: `pytest`, `pytest-cov`, `hypothesis`, `ruff`, `mypy`, `pre-commit`, `freezegun`.

### Coding standards

- Type hints everywhere; `mypy --strict` on `src/`. `ruff` for lint and format, line length 100.
- Every public function has a docstring: one line of purpose, then Args, Returns, Raises. The owner writes docs for a living; match that bar.
- No global mutable state. Dependency injection through constructors; the `Clock`, `MarketAdapter`, and `Notifier` are protocols with real and fake implementations.
- Pure functions for anything numeric. Side effects live only in `execution/`, `live/`, `notify/`, and `data/` fetchers.
- All timestamps are timezone-aware UTC `datetime` or `pd.Timestamp`; naive datetimes are a lint error (write a custom ruff rule or a test that greps for `datetime.now()` without `tz`).
- Money and quantities as `Decimal` at the execution boundary, `float64` inside numeric code. Convert once, at the adapter.
- Errors: a small exception hierarchy in `kestrel/errors.py` (`KestrelError`, `DataError`, `AdapterError`, `RiskBreach`, `ConfigError`). Never catch bare `Exception` except at the top of the live runner, where it is logged and re-raised after notifying.
- Logging via `structlog` to JSON lines on disk and pretty console. Never log secrets; redact anything matching `KEY|SECRET|TOKEN`.
- Conventional commits (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`).

## 6. Data layer

The data layer turns a `(market, symbol, timeframe, start, end)` request into a clean, cached pandas DataFrame, and never silently returns a gap.

### Sources

| Market | Source | Access | Notes |
| --- | --- | --- | --- |
| Crypto | Exchange public REST via CCXT (default Binance, configurable) | No key for history | Years of 1h and 1d bars; 1m bars for recent months only |
| US equities, daily | Alpaca Market Data (free tier, IEX feed) | Paper key | Daily bars back to 2016 on free tier; confirm limits at build time |
| US equities, fallback | `yfinance` | None | Research only; never for live decisions, data quality is uneven |
| Calendar | `pandas_market_calendars` for NYSE; crypto is 24/7 | None | Used by backtester and scheduler |

### Schema

One canonical OHLCV frame everywhere. Columns: `ts` (UTC, bar open time, index), `open`, `high`, `low`, `close`, `volume`, `symbol`, `market`, `timeframe`. Parquet on disk at `data/cache/{market}/{symbol}/{timeframe}.parquet`, partitioned by year if a file exceeds 50 MB.

### Behaviour

- Fetch is incremental: read the cache, request only the missing tail, append, rewrite the partition.
- Validation on every load: monotonic timestamps, no duplicates, no negative prices, `low <= open,close <= high`, gaps flagged. A gap larger than one bar raises `DataError` unless `allow_gaps: true` in config, in which case the gap is forward-filled and logged.
- Universe definitions live in YAML: a static list for v1 (`BTC/USDT, ETH/USDT, SOL/USDT, …` and a 30-stock US list). Note in the knowledge base that a static list has survivorship bias; a point-in-time universe is a v2 item.
- Rate limiting: a token bucket per source; CCXT's `enableRateLimit=True` plus our own backoff on HTTP 429.
- Everything is reproducible: a `data/manifest.json` records source, fetch time, and row counts per file.

### Fixtures for tests

`scripts/fetch_fixtures.py` downloads 2 years of daily bars for 5 crypto pairs and 10 stocks once, trims them, and commits them under `tests/fixtures/` (target under 2 MB total). Tests never hit the network.

## 7. Feature layer

Features are pure functions `DataFrame -> DataFrame` that add columns and never look forward. Every feature declares its lookback so the backtester can warm up correctly.

- Returns: simple and log returns at 1, 5, 20 bars; rolling volatility (20, 60 bars, annualised).
- Trend: SMA, EMA (configurable windows), MACD, ADX.
- Mean reversion: Bollinger bands (window, k), z-score of close against rolling mean, RSI.
- Volume: rolling volume z-score, dollar volume.
- Regime flags: volatility regime (rolling vol tercile), trend regime (price above or below 200-bar SMA). Used by strategies to switch behaviour and by reports to break down performance.
- Cross-sectional (for the ranker): per-timestamp rank and z-score of momentum and volatility across the universe.

Rules the agent must enforce in code and in tests:

- A feature at bar `t` may use data up to and including bar `t`'s close only. A test shifts the input and asserts no change in earlier rows.
- Features are computed once per run and cached in memory keyed by `(symbol, timeframe, feature spec hash)`.
- Every feature function is registered in a `FEATURES` registry with name, parameters, and lookback, so a strategy can declare `requires = ["sma_20", "sma_50"]` and the engine resolves them.

## 8. Strategy layer

A strategy is a class that turns features into target weights. It never touches orders, balances, or the clock directly; the engine does. Same class runs in backtest and paper.

### Contract

```python
class Strategy(Protocol):
    name: str
    requires: list[str]          # feature names from the registry
    timeframe: str               # "1d", "1h"
    universe: str                # key into configs/universes
    params: BaseModel            # pydantic, validated from yaml

    def warmup_bars(self) -> int: ...
    def on_bar(self, ctx: BarContext) -> dict[str, float]:
        """Return target weight per symbol in [0, 1]; omitted symbols mean 0.
        Sum may be below 1 (cash). Sum above 1 is a ConfigError."""
    def on_fill(self, fill: Fill) -> None: ...    # optional hook, default no-op
    def state(self) -> dict: ...                 # serialisable, for restart
    def load_state(self, s: dict) -> None: ...
```

`BarContext` carries: current UTC timestamp, the feature frame for every symbol in the universe up to and including this bar, current positions and cash as read-only views, and the regime flags. It carries nothing from the future; a test asserts the frame's last index equals `ctx.ts`.

Strategies register with a decorator and are selected by name from config. Strategy params are a pydantic model so the CLI can print the schema and validate YAML before a run starts.

### Reference strategies (all three must ship)

| Name | Type | Logic | Purpose |
| --- | --- | --- | --- |
| `sma_cross` | Trend, per-symbol | Long when SMA(fast) > SMA(slow), flat otherwise; equal weight across symbols in a long state | Simplest possible end-to-end check |
| `boll_revert` | Mean reversion, per-symbol | Enter long when close < lower band and RSI < 30; exit at mid band or after N bars | Exercises time-based exits and regime filter (disabled in high-vol regime) |
| `xs_rank` | Cross-sectional ML | LightGBM regressor predicts next-20-bar return rank from momentum, vol, volume features; hold top-k equal weight, rebalance weekly | Exercises ML path, walk-forward retraining, and the overfit detector |

`xs_rank` training rules: train only on data strictly before the prediction timestamp, with an embargo gap equal to the label horizon (20 bars) so labels never overlap the training window. Retrain on a fixed cadence (default every 60 bars). Persist the model per fold under `artifacts/models/`.

### Deliberately bad strategy (test fixture)

`tests/fixtures/overfit_strategy.py`: a lookup table of the best in-sample days memorised from the fixture data. It must show a spectacular in-sample Sharpe and the validation layer must flag it. If validation passes it, validation is broken.

### Strategy docs

`docs/strategies.md` describes each strategy in one page: hypothesis, parameters with defaults and sane ranges, what regime it should and should not work in, known failure modes. Write it as the owner would: for a developer reader, no hype.

## 9. Backtester

The backtester is event-driven, bar by bar, with decisions at bar close and fills at the next bar's open. It is the component most likely to lie, so it gets the most tests.

### Event loop

1. For each bar `t` in the merged calendar of the universe: build `BarContext(t)`.
2. Call `strategy.on_bar(ctx)` to get target weights.
3. Risk layer converts targets to orders (sizing, limits) or vetoes them.
4. Orders queue for execution at bar `t+1` open (configurable: `fill_at: next_open | this_close`; default `next_open`; `this_close` is only for diagnostics and prints a warning).
5. Fill model computes fill price and partial fills; fees and slippage applied.
6. Portfolio updates positions, cash, equity; records the trade.
7. Mark-to-market at `t+1` close; append to equity curve.

### Fill, fee, and slippage models

- Fill price = next open adjusted by slippage. Slippage default: `bps + k * (order_notional / bar_dollar_volume)` with `bps=5`, `k=0.1`, capped at 50 bps. Both configurable per market.
- Fees: crypto taker 0.10% default; equities 0 commission plus half-spread model of 2 bps. Per-market config.
- Partial fills: an order larger than `max_participation * bar_volume` (default 5%) fills only that fraction; the remainder is cancelled and logged. This is deliberate: it stops strategies that would only work with infinite liquidity.
- Minimum notional and lot size rounding per symbol, read from the adapter's market metadata (CCXT `load_markets`, Alpaca asset info) and frozen into the fixtures.
- No shorting in v1: a negative target weight is clamped to 0 and counted in a `clamped_shorts` metric so the owner can see the strategy wanted to short.

### Portfolio accounting

- Cash, positions (qty, avg cost), realised and unrealised PnL, equity, exposure, turnover.
- Equity curve as a DataFrame indexed by bar close with columns `equity, cash, exposure, drawdown, n_positions`.
- Trade log: `ts_signal, ts_fill, symbol, side, qty, price, fee, slippage_cost, reason` where `reason` is `signal | rebalance | risk_exit | eod_flat`.

### Metrics (in `reporting/metrics.py`, all pure functions over the equity curve and trade log)

CAGR, annualised volatility, Sharpe (rf = 0; annualisation factor by timeframe: 365 for crypto daily, 252 for equities daily, 8,760 for crypto hourly, 1,638 for equities hourly), Sortino, max drawdown and its duration, Calmar, hit rate, average win and loss, profit factor, turnover, exposure, number of trades, fees as a percentage of gross PnL, performance by regime.

### Determinism

Same config, same data, same seed produces byte-identical reports. A test runs a backtest twice and diffs the JSON output.

### Performance target

3 strategies, 20 symbols, 4 years of daily bars: under 60 seconds total on a laptop. Vectorise feature computation with pandas; keep the event loop in plain Python (clarity over speed in v1). Profile with `cProfile` and record the baseline in `BUILD_LOG.md`.

## 10. Validation and overfitting checks

This layer is the product's differentiator. A backtest number without a validation verdict is not shown in any report.

### Methods (all in `validation/`)

1. Walk-forward analysis. Split the period into N windows (default 6). For each window, fit or tune on the in-sample part and evaluate on the following out-of-sample part. Report the out-of-sample Sharpe per window, the ratio of OOS to IS Sharpe, and the fraction of windows with positive OOS return. Anchored and rolling variants.
2. Purged k-fold cross-validation with embargo for the ML strategy: folds are contiguous in time, training samples whose label windows overlap the test fold are purged, and an embargo of `label_horizon` bars follows each test fold.
3. Deflated Sharpe ratio: given the number of strategy variants tried (read from the parameter grid size or passed explicitly), the skew and kurtosis of returns, and the sample length, compute the probability that the observed Sharpe beats zero after accounting for selection. Report as a probability; below 0.95 is flagged.
4. Parameter sensitivity: evaluate the strategy on a small grid around the chosen parameters (default plus or minus 20% on each numeric param). If the chosen point is a sharp peak (Sharpe falls more than 50% at neighbours), flag it. Plot the surface as a heatmap in the HTML report.
5. Monte Carlo on trade order: shuffle the trade sequence 1,000 times and report the 5th-percentile max drawdown and the probability of ruin at the configured drawdown limit.
6. Bootstrap confidence interval on Sharpe (block bootstrap, block length 20 bars, 1,000 resamples).

### Verdict

`ValidationReport.verdict` is one of `pass | caution | fail` with the reasons listed. Rules (configurable thresholds):

- `fail` if deflated Sharpe probability < 0.90, or OOS/IS Sharpe ratio < 0.3, or the overfit fixture pattern is matched, or fewer than 30 trades.
- `caution` if any single check is marginal.
- `pass` otherwise.

The `run` command refuses to start a paper loop for a strategy whose last validation verdict is `fail`, unless `--i-understand-this-is-overfit` is passed, which is logged loudly.

### Tests

- The overfit fixture must produce `fail`.
- A random-walk strategy (coin-flip signals) on synthetic data must produce `fail` or `caution`, never `pass`, across 20 seeds.
- A known-good synthetic signal (a planted drift the strategy is designed to catch) must produce `pass`.

## 11. Risk layer

The risk layer sits between strategy and execution in both backtest and paper, and it has veto power. It is the only component allowed to flatten the book.

### Position sizing (pick one per config)

- `fixed_fraction`: each target weight is used as given, scaled so total exposure is at most `max_gross_exposure` (default 1.0).
- `vol_target`: scale each position so its contribution matches a target annualised volatility (default 15% portfolio, using 20-bar realised vol per symbol), capped at `max_weight_per_symbol`.

### Hard limits (all configurable, all enforced before an order is created)

| Limit | Default | Action on breach |
| --- | --- | --- |
| Max weight per symbol | 25% | Clamp the order |
| Max gross exposure | 100% | Scale all orders down pro rata |
| Max orders per bar | 20 | Drop the smallest |
| Max daily loss | 3% of start-of-day equity | Flatten all, halt until next day |
| Max drawdown from peak | 15% | Flatten all, halt until owner `/resume` |
| Max consecutive adapter errors | 5 | Halt, notify |
| Stale data | last bar older than 2 bar lengths | Skip the bar, notify after 3 skips |
| Order notional below exchange minimum | per market metadata | Drop and log |

### Kill-switch

`risk.halt(reason)` cancels open orders, submits market orders to flatten every position, writes `HALTED` and the reason to the state store, and notifies. The live runner checks the halt flag before every cycle and does nothing while halted except respond to Telegram. `/resume` clears the flag and requires the owner to type the reason back as confirmation.

### Tests

- Property test with hypothesis: for any set of target weights, post-risk orders never exceed any limit.
- A synthetic crash day triggers the daily-loss halt within the same bar.
- Halt is idempotent: calling it twice does not double-submit flatten orders.

## 12. Execution adapters

One protocol, three implementations: `MockAdapter` (tests and backtest), `CcxtAdapter` (crypto, sandbox only), `AlpacaAdapter` (equities and crypto, paper only). The protocol is the only thing `live/` depends on.

```python
class MarketAdapter(Protocol):
    market: Literal["crypto", "equities"]
    def is_open(self, ts: datetime) -> bool: ...
    def next_open(self, ts: datetime) -> datetime: ...
    def get_bars(self, symbol, timeframe, start, end) -> pd.DataFrame: ...
    def get_quote(self, symbol) -> Quote: ...               # bid, ask, ts
    def get_positions(self) -> list[Position]: ...
    def get_balance(self) -> Balance: ...                   # cash, equity
    def place_order(self, req: OrderRequest) -> Order: ...  # market or limit, idempotency key
    def cancel_order(self, order_id) -> None: ...
    def get_order(self, order_id) -> Order: ...
    def get_open_orders(self) -> list[Order]: ...
    def market_meta(self, symbol) -> MarketMeta: ...       # min notional, lot size, tick size, fees
```

### Safety gate (non-negotiable)

Each real adapter's constructor validates its endpoint against an allowlist:

- `AlpacaAdapter`: base URL must be `https://paper-api.alpaca.markets`. Anything else raises `ConfigError` before any network call.
- `CcxtAdapter`: `exchange.set_sandbox_mode(True)` is called and the resulting URL must contain `testnet` or `sandbox`; otherwise raise. Exchanges without a sandbox in CCXT are rejected by name.
- There is no configuration path to a live endpoint. The check is a unit test that tries every known live URL and asserts `ConfigError`.

### Idempotency and reconciliation

- Every `OrderRequest` carries a client order id of the form `kst-{strategy}-{symbol}-{bar_ts}-{n}`. Both Alpaca and most CCXT exchanges accept a client id; the adapter de-duplicates on it so a retried request after a timeout cannot double-fill.
- `get_positions` and `get_balance` are the source of truth. The reconciler (section 13) compares them to local state every cycle.

### CCXT specifics

- Default exchange `binance` sandbox; `bybit` and `okx` as tested alternatives. Symbol format `BASE/QUOTE`.
- Use `fetch_ohlcv` with pagination for history; respect `exchange.rateLimit`.
- Testnet balances are fake and refill on request; document how the owner tops up.

### Alpaca specifics

- Use `alpaca-py` `TradingClient(paper=True)` and `StockHistoricalDataClient` / `CryptoHistoricalDataClient`.
- Equities: market orders only in v1; time in force `day`; fractional quantities allowed for market orders only. Respect the NYSE calendar; never submit outside regular hours.
- Crypto via Alpaca is an alternative to CCXT for the owner's convenience; one paper key covers both.
- The owner creates the paper account himself and puts `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` in his own environment. The agent never sees them.

### Tests

- `MockAdapter` is deterministic and scriptable: tests can inject rejections, partial fills, timeouts, and stale quotes.
- Contract tests run the same suite against `MockAdapter` and, when `KESTREL_INTEGRATION=1` and paper keys are present in the owner's environment, against the real paper adapters. CI runs only the mock suite.

## 13. Live paper loop

`kestrel run --config configs/paper_crypto.yaml` starts a long-running process that executes one cycle per bar, survives crashes and reboots, and never acts on state it has not reconciled with the broker.

### Cycle (one per bar close, scheduled by APScheduler on the market calendar)

1. Reconcile: pull positions, balance, open orders from the adapter; diff against the local state store; on mismatch, trust the broker, log a `reconcile_drift` event with the diff, and notify if drift exceeds 1% of equity.
2. Check halt flag. If halted, sleep until next cycle.
3. Fetch the latest bars (incremental, through the data layer). Verify the newest bar is the expected one; if stale, apply the stale-data rule.
4. Build features, call `strategy.on_bar`, pass targets through risk.
5. Submit orders with idempotency keys. Poll until filled, cancelled, or timeout (default 60 s; then cancel and log).
6. Persist state (positions, cash, strategy state, last bar ts, open order ids) in one SQLite transaction.
7. Emit a cycle summary to the log and, if anything changed, to Telegram.

### State store

SQLite at `state/kestrel.db` via `sqlite3` with WAL mode. Tables: `runs`, `cycles`, `orders`, `fills`, `positions_snapshot`, `equity`, `events`, `halt`. Every write is a transaction keyed by `(run_id, bar_ts)`; a crash mid-cycle leaves either the previous or the new state, never a mix. A `kestrel state show` command prints it.

### Restart safety

- On start, read the last persisted bar ts. If the current time is more than one bar past it, run reconcile first and log that cycles were missed; do not try to replay them.
- Open orders from a previous run are looked up by client id; filled ones are recorded, stale ones cancelled.
- A lock file prevents two instances on the same config.
- Process supervision is the owner's choice and documented in `docs/runbook.md`: `systemd` unit on Ubuntu, NSSM or Task Scheduler on Windows, `docker compose up -d` on a VPS. All three with `Restart=always` equivalents.

### Clock

All scheduling goes through the `Clock` protocol. `SimClock` lets the whole live loop run in tests at any speed with `freezegun`; a 7-day paper run is simulated in seconds against `MockAdapter` in CI.

### Daily report

At a configured local time (default 08:00 Asia/Bangkok) send a Telegram summary: equity, day and week PnL, drawdown from peak, open positions, trades in the last 24 h, warnings. Weekly: regenerate the HTML report for the running strategy and send a link or the file.

## 14. Interfaces: CLI and Telegram

The CLI is the PC interface and the only way to start or change anything. Telegram is the phone interface: read-only plus halt and resume.

### CLI (`typer`, `rich` output)

| Command | Does |
| --- | --- |
| `kestrel init` | Creates `configs/`, `.env` from `.env.example`, `data/`, `state/`; checks Python version, writes a doctor report |
| `kestrel doctor` | Checks environment: which optional keys are present, which adapters can connect to their paper endpoints, cache size, disk space; never prints key values |
| `kestrel data fetch --market crypto --universe crypto_top20 --timeframe 1d --from 2022-01-01` | Fills the cache |
| `kestrel data check` | Validates cache integrity, prints gaps |
| `kestrel backtest --config configs/backtest_crypto.yaml [--strategy X] [--from] [--to]` | Runs one backtest, writes `reports/<run_id>/report.html` and `metrics.json`, prints a summary table |
| ` kestrel validate --config …  ` | Runs the full validation suite, writes verdict |
| `kestrel sweep --config … --param fast=5:30:5 --param slow=50:200:25` | Grid run, writes a sensitivity table and heatmap |
| `kestrel run --config configs/paper_crypto.yaml` | Starts the paper loop (foreground; supervision is external) |
| `kestrel halt --reason "…"` / `kestrel resume` | Sets or clears the halt flag through the state store |
| `kestrel state show` | Prints positions, cash, last cycle, halt status |
| `kestrel report --run-id …` | Regenerates the HTML report |
| `kestrel strategies list` / `kestrel strategies schema X` | Lists strategies, prints the param schema |

Every command has `--help` with an example. `--json` on read commands prints machine-readable output. Exit codes: 0 ok, 1 user error, 2 data error, 3 adapter error, 4 risk halt.

### Telegram bot (`python-telegram-bot`, long polling, no public webhook)

Commands: `/status`, `/equity`, `/positions`, `/trades [n]`, `/signals`, `/halt <reason>`, `/resume <reason>`, `/report` (sends the latest HTML as a file), `/help`.

Rules:

- Only the chat id in `KESTREL_TELEGRAM_CHAT_ID` is accepted; every other sender is ignored and logged once.
- No command places an order. `/halt` and `/resume` are the only state changes.
- Messages are plain text with a fixed-width block for tables so they read on a phone. Keep each under 40 lines.
- Push alerts: halt, reconcile drift, adapter error streak, daily report, weekly report.
- Transport is injected; tests use a fake bot that records sent messages.
- If `KESTREL_TELEGRAM_TOKEN` is absent, the `NullNotifier` is used and the bot runs on. Telegram is optional.

### Mobile use without Telegram

The HTML report is responsive (single column under 600 px, plotly charts with `responsive: true`) so it reads on a phone from any file share. No web server is needed.

## 15. Config, secrets, and optional integrations

Everything the bot needs is YAML plus environment variables. Everything it could use but does not need is behind a feature flag that defaults to off, and the bot runs fully without any of it.

### Config files

Pydantic models in `config.py`; YAML is parsed, validated, and printed back with defaults filled so the owner can see what a run will do. Sections: `market`, `adapter`, `data`, `universe`, `strategy` (name plus params), `risk`, `backtest` (dates, fees, slippage), `validation` (thresholds), `live` (schedule, timeouts), `notify`, `integrations`, `display_tz`.

### Environment variables (`.env.example`, names only)

| Variable | Required | Used by |
| --- | --- | --- |
| `APCA_API_KEY_ID`, `APCA_API_SECRET_KEY` | For Alpaca paper runs | `AlpacaAdapter` |
| `KESTREL_CCXT_EXCHANGE`, `KESTREL_CCXT_API_KEY`, `KESTREL_CCXT_SECRET` | For CCXT sandbox runs | `CcxtAdapter` |
| `KESTREL_TELEGRAM_TOKEN`, `KESTREL_TELEGRAM_CHAT_ID` | Optional | Telegram notifier |
| `ANTHROPIC_API_KEY` | Optional | `integrations/llm.py` |
| `OPENAI_API_KEY` | Optional, alternative | `integrations/llm.py` |
| `KESTREL_NEWS_API_KEY` | Optional | `integrations/news.py` |
| `KESTREL_DISPLAY_TZ` | Optional, default `Asia/Bangkok` | Reports |
| `KESTREL_INTEGRATION` | Optional, `1` enables real-paper contract tests | Test suite |

Secrets are read once at startup through `pydantic-settings`, held in a `SecretStr`, and never serialised. `kestrel doctor` reports presence only. `.env` is gitignored; a pre-commit hook (`detect-secrets` or a regex hook) blocks commits containing key-like strings.

### Optional AI integration (`integrations/llm.py`)

Purpose: explanation and summarisation, never decisions. When a key is present and `integrations.llm.enabled: true`:

- Daily and weekly reports get a short plain-language narrative generated from the metrics JSON (what moved, which positions drove PnL, which warnings fired). The numbers are computed by the bot; the model only writes prose around them.
- `kestrel explain --run-id …` produces a human-readable walkthrough of a backtest and its validation verdict.
- `kestrel strategies describe X` drafts the `docs/strategies.md` page for a new strategy from its code and docstrings, for the owner to edit.

Constraints: provider-agnostic through a tiny `LLMClient` protocol with Anthropic and OpenAI implementations; hard monthly token budget in config (default 200k tokens) with a counter in the state store; every call is logged with token counts; the model never sees keys, account identifiers, or the raw trade log beyond aggregates; a provider failure degrades to the non-AI report with one warning line. With no key, every AI feature is simply absent from the CLI help and the reports, with no errors.

### Optional data integrations (`integrations/news.py` and future)

Same pattern: a `NewsSource` protocol, one implementation behind a key, used only to attach headlines to the daily report for context, never as a signal in v1. Add a `docs/integrations.md` page that says how to add another source in under 50 lines.

### Cost ceiling

The bot must cost the owner nothing to run beyond electricity or a small VPS: free data tiers, paper accounts, optional AI under a capped budget. `kestrel doctor` prints the estimated monthly AI spend from the counter.

## 16. Logging, reports, alerts

Logs are for the agent and the owner debugging; reports are for the owner deciding; alerts are for the owner's phone. Each has one format.

### Logs

- `structlog`, JSON lines to `logs/kestrel-YYYY-MM-DD.jsonl`, rotated daily, 30 days kept; pretty console in the foreground.
- Every event carries `run_id`, `cycle_id`, `bar_ts`, `strategy`, `market`. Order events carry the client order id.
- Levels: `DEBUG` for feature values and adapter payloads (off by default), `INFO` for cycle summaries and orders, `WARNING` for skipped bars, drift, degraded integrations, `ERROR` for adapter failures, `CRITICAL` for halts.
- A redaction processor removes anything matching `(?i)(key|secret|token|password)\s*[=:]`.

### HTML report (`reporting/html.py`, Jinja2 plus Plotly)

One self-contained file per run, under 5 MB, no external requests. Sections in order: verdict banner (pass, caution, fail with reasons), headline metrics table, equity curve with drawdown shading, monthly returns heatmap, performance by regime, trade list (sortable), parameter sensitivity heatmap, walk-forward table, Monte Carlo drawdown distribution, configuration dump, data manifest. Responsive single column under 600 px.

### JSON export

`metrics.json` with the same numbers, stable key names, a `schema_version`. Used by tests for determinism and by the optional AI narrative.

### Alerts

Sent through the `Notifier` protocol (`TelegramNotifier`, `ConsoleNotifier`, `NullNotifier`). Alert types and default severity: `halt` (critical), `reconcile_drift` (warning), `adapter_error_streak` (warning), `stale_data` (warning after 3), `daily_report` (info), `weekly_report` (info), `budget_80pct` for AI spend (info). Alerts are rate-limited: no more than one of the same type per 15 minutes except `halt`.

## 17. Testing and CI

The test suite is the proof that the backtester does not lie and the live loop does not lose state. Target 85% line coverage on `src/`, 100% on `backtest/`, `risk/`, and `validation/`.

### Layout and tooling

- `pytest` with `pytest-cov`, `pytest-xdist` for parallel, `hypothesis` for property tests, `freezegun` for time, `respx` for mocking `httpx`, `pytest-benchmark` for the performance target.
- Markers: `unit` (default, no network, under 10 s total), `integration` (mock adapters and SimClock, under 2 min), `contract` (real paper endpoints, only with `KESTREL_INTEGRATION=1`, never in CI), `slow`.
- Fixtures: frozen parquet files under `tests/fixtures/`, a `make_synthetic_ohlcv(seed, drift, vol, n)` helper, the overfit strategy, scripted `MockAdapter` scenarios in YAML.

### Unit tests, by module

| Module | Must cover |
| --- | --- |
| `data` | Incremental fetch appends only the tail; validation rejects duplicates, non-monotonic ts, bad OHLC; gap detection; manifest written; rate limiter sleeps on 429 (mocked) |
| `features` | Each feature matches a hand-computed reference on a 10-row frame; no-lookahead test (truncate input, earlier outputs unchanged); registry resolves dependencies |
| `strategies` | Each reference strategy produces expected weights on a crafted frame; weights in \[0, 1\]; sum at most 1; state round-trips through `state()` and `load_state()` |
| `backtest` | Next-open fill; slippage and fee arithmetic against hand calculations; partial fill cap; lot and min-notional rounding; short clamp counted; equity curve identity (cash + positions = equity) on every bar; determinism diff; a 1-symbol 5-bar scenario with every number asserted by hand |
| `validation` | Walk-forward windows tile the period without overlap; purge removes overlapping labels (constructed case); embargo length; deflated Sharpe against a published worked example; sensitivity flags a planted peak; overfit fixture fails; random-walk never passes across 20 seeds; planted-drift passes |
| `risk` | Hypothesis: no post-risk order breaches any limit for any input; daily-loss halt fires same bar; drawdown halt; halt idempotent; vol-target sizing arithmetic |
| `execution` | Endpoint allowlist rejects every known live URL; idempotency key format; mock scenarios: rejection, partial, timeout then success, stale quote |
| `live` | Full 7-day simulated run with SimClock and MockAdapter; crash injected mid-cycle leaves consistent state; restart after missed bars reconciles and does not replay; lock file blocks a second instance; orphaned open order from previous run is handled |
| `notify` | Telegram handlers with fake transport; unknown chat id ignored; rate limiting; NullNotifier when no token |
| `integrations` | Absent key means feature absent from CLI and report; budget cap stops calls; provider failure degrades with one warning; mocked provider responses |
| `config` | YAML round-trip with defaults; bad params produce a readable error naming the field; secrets never appear in `repr` or logs |
| `cli` | `typer` test runner: every command's `--help`; `--json` output is valid JSON; exit codes |

### Integration tests

- End to end: `data fetch` (fixtures) then `backtest` then `validate` then `report`, asserting the report file exists, is under 5 MB, contains the verdict banner, and `metrics.json` matches a golden file within 1e-9.
- Paper loop against MockAdapter for 7 simulated days per reference strategy.

### Contract tests (owner's machine only)

Same adapter suite against Alpaca paper and one CCXT sandbox, read-only plus one tiny round-trip order that is cancelled. Skipped unless `KESTREL_INTEGRATION=1`.

### CI (`.github/workflows/ci.yml`)

- Matrix: `ubuntu-latest` and `windows-latest`, Python 3.11 and 3.12.
- Steps: `uv sync`, `ruff check`, `ruff format --check`, `mypy --strict src`, `pytest -m "unit or integration" --cov`, coverage gate, benchmark job on Ubuntu only with the 60 s target.
- A secrets scan step fails the build on key-like strings.
- `pre-commit` config mirrors the lint steps for local use.

## 18. Milestones and acceptance criteria

Build in this order. Each milestone ends with a PR to `develop`, green CI on both OSes, a `BUILD_LOG.md` line, and the acceptance checks below passing. Do not start the next milestone with the previous one's checks failing.

1. Skeleton. Repo layout, `pyproject.toml`, `uv.lock`, CI matrix, `kestrel --help`, `kestrel init`, `kestrel doctor` (reports nothing configured), pre-commit. Accept: CI green on both OSes with zero tests skipped.
2. Data layer. Fetchers, cache, validation, manifest, fixtures script, `data fetch` and `data check`. Accept: fixtures committed under 2 MB; all data unit tests pass; a second `fetch` call makes zero network requests (mocked counter).
3. Features and strategies. Registry, all features, `Strategy` protocol, `sma_cross` and `boll_revert`, `strategies list` and `schema`. Accept: no-lookahead tests pass for every feature; strategy unit tests pass.
4. Backtester and metrics. Engine, fill models, portfolio, metrics, JSON export, determinism. Accept: the hand-asserted 5-bar scenario passes; determinism diff is empty; benchmark under 60 s.
5. HTML report. Jinja2 and Plotly report, responsive. Accept: report under 5 MB, opens offline, renders on a 375 px viewport (Playwright screenshot test or manual note in BUILD\_LOG).
6. Validation. All six methods, verdict, overfit fixture, `validate` and `sweep` commands. Accept: overfit fixture fails; random-walk never passes; planted drift passes; `run` refuses a failed strategy.
7. ML strategy. `xs_rank` with LightGBM, purged CV, retraining cadence, model persistence under the `[ml]` extra. Accept: trains on fixtures in under 30 s; embargo test passes; core installs without the extra.
8. Risk layer. Sizing, limits, kill-switch. Accept: hypothesis property test passes 500 examples; halt tests pass.
9. Adapters. Protocol, MockAdapter scenarios, CcxtAdapter sandbox, AlpacaAdapter paper, endpoint allowlist. Accept: allowlist test rejects every live URL; mock scenario suite passes; contract test documented for the owner.
10. Live loop. Scheduler, state store, reconciler, restart safety, lock file, daily report. Accept: 7-day SimClock run per strategy passes; crash-injection test passes; `state show` works.
11. Telegram and notifiers. Accept: fake-transport tests pass; bot runs with no token as NullNotifier.
12. Optional integrations. LLM narrative and explain, news headlines, budget cap. Accept: absent-key tests pass; mocked-provider tests pass; `doctor` reports presence and spend.
13. Docs and runbook. README, ARCHITECTURE, KNOWLEDGE\_BASE, strategies, runbook with Windows and Ubuntu and Docker supervision, thailand, integrations, OWNER\_TODO finalised. Accept: a fresh clone on each OS reaches a passing `kestrel backtest` on fixtures by following the README alone.
14. Release 0.1.0. Tag on `main`, CHANGELOG, `uv build` produces a wheel, `pipx install` works. Accept: the owner can install from the wheel and run the quickstart.

After milestone 14 the agent stops. It does not start the paper loop. It writes a final `OWNER_TODO.md` listing exactly what the owner must do to start a paper run: create the paper accounts, set the environment variables, run `doctor`, run `validate`, then `run`.

## 19. README outline

The README is written for two readers: Med on a fresh machine in six months, and a stranger on GitHub judging the repo in ninety seconds. It must get the stranger to a passing backtest on fixtures in under five minutes.

```markdown
# kestrel

Backtest, validate, and paper-trade strategies across crypto and US equities,
and find out when your backtest is lying.

> Paper trading only. kestrel has no live-money mode and refuses non-paper endpoints.
> Nothing here is financial advice.

## Why
Three sentences: most hobby bots optimise the strategy and ignore the backtester;
kestrel inverts that. The validation layer is the product. The rest is plumbing
built so it can be trusted.

## Quickstart (5 minutes, no accounts needed)
  Windows PowerShell block and Ubuntu bash block, side by side:
  uv sync, kestrel init, kestrel data fetch (fixtures), kestrel backtest, open the report.

## What it does
  One screenshot of the report verdict banner (committed PNG under docs/img/).
  Bullet list: backtester, validation, risk, paper loop, Telegram, optional AI.

## Paper trading
  Create an Alpaca paper account / a CCXT testnet key, set env vars, kestrel doctor,
  kestrel validate, kestrel run. Link to docs/runbook.md for supervision.

## From Thailand
  Three lines + link to docs/thailand.md.

## Writing a strategy
  The Strategy protocol in 15 lines, link to docs/strategies.md.

## Optional integrations
  AI narrative (Anthropic or OpenAI key), news headlines. What they add, what they cost,
  what happens without them (nothing breaks).

## Architecture
  One diagram (docs/img/architecture.svg) and a link to docs/ARCHITECTURE.md.

## Development
  uv, ruff, mypy, pytest markers, CI matrix, branch model, conventional commits.

## Roadmap
  v2 candidates: shorting, point-in-time universes, more adapters, Bitkub.

## Licence
  MIT.
```

Style: AU/UK spelling, no exclamation marks, no emoji, code blocks tested by copying them into a fresh shell, every command shown with its expected first line of output. A short personal note at the end in Med's voice is fine (why he built it, link to asohail.dev and cvforge); the agent drafts it and marks it for his edit.

## 20. Knowledge base

These are the facts and failure modes the agent designs around. Expand this into `docs/KNOWLEDGE_BASE.md` with a short worked example per item. Where a claim is about a provider's current behaviour, verify it against their docs at build time and cite the page.

### Why most trading bots fail

- Lookahead bias: using information from bar `t+1` to decide at bar `t`. Common sources: computing indicators on the full series then slicing, filling at the same bar's close, using adjusted prices computed with future splits. Defence: features are computed causally, fills at next open, tests that truncate input.
- Survivorship bias: a universe chosen today only contains survivors. A static list of current top-20 coins backtested over 2020 ignores everything that died. Defence: document it, make universes dated, plan point-in-time universes for v2.
- Overfitting and selection bias: try 200 parameter sets, report the best. Defence: deflated Sharpe with the number of trials, walk-forward, sensitivity surface, embargoed CV.
- Ignoring costs: fees, spread, slippage, and market impact turn many positive backtests negative. Crypto taker fees of 0.1% on a strategy that turns over daily cost around 36% a year. Defence: realistic default cost models, fees reported as a percentage of gross PnL.
- Liquidity: a backtest can buy 10% of a day's volume at the open price. Real fills cannot. Defence: participation cap and partial fills.
- Regime dependence: a trend strategy fitted on 2020 to 2021 crypto looks brilliant and dies in 2022. Defence: performance by regime in every report, walk-forward across regimes.
- Operational failure: the bot crashes at 3 am, restarts, and double-buys. Defence: idempotency keys, reconcile-first cycles, transactional state.

### Why linear regression on prices does not work

Short-horizon returns are close to white noise; realistic out-of-sample R² for return prediction is in the low thousandths. A model that fits well in-sample is fitting noise. Regression and gradient boosting earn their place for cross-sectional ranking (which asset is relatively stronger), regime classification, and volatility forecasting, where there is persistent structure. Deep sequence models on raw prices are out of scope for this reason, not for lack of compute.

### Validation methods, in one line each

- Walk-forward: fit on window k, test on window k+1, repeat; the only honest single-strategy test.
- Purged k-fold with embargo (López de Prado): remove training samples whose labels overlap the test fold and leave a gap after it, so overlapping labels cannot leak.
- Deflated Sharpe ratio (Bailey and López de Prado): adjusts the Sharpe for the number of trials, non-normality, and sample length; outputs a probability.
- Parameter sensitivity: a real edge is a plateau, an overfit one is a spike.
- Block bootstrap: resample contiguous blocks of returns to keep autocorrelation when estimating a confidence interval.
- Monte Carlo trade shuffle: the order of trades is luck; the distribution of drawdowns under reshuffling is the risk.

### Market mechanics the code must respect

| Topic | Crypto | US equities |
| --- | --- | --- |
| Hours | 24/7; bar boundaries in UTC | NYSE 09:30 to 16:00 America/New\_York, early closes, holidays; use the exchange calendar |
| Fees | Maker and taker, typically 0.02% to 0.1%; testnets mimic them | Commission-free on retail APIs; cost is spread and payment-for-order-flow effects |
| Lot rules | Per-market min notional, step size, tick size from `load_markets` | Whole shares or fractional market orders; min notional $1 on Alpaca |
| Settlement | Instant | T+1 since May 2024; affects cash available for re-buying on paper too |
| Pattern day trader | Not applicable | Four or more day trades in five business days with under $25,000 equity triggers restrictions on margin accounts; paper accounts simulate this. Default the equities strategy to daily rebalancing to stay clear |
| Shorting | Perpetual futures; out of scope | Needs margin and borrow; out of scope |
| Data gaps | Exchange outages leave missing bars | Halts, delistings |
| Annualisation | 365 days | 252 days |

### Access from Thailand

Binance, Bybit, and OKX serve Thai users through their global sites and expose public testnets; Binance also runs a locally licensed entity (Binance TH) with THB pairs and a separate API. Bitkub is the largest Thai-licensed exchange. Alpaca paper accounts are open worldwide; Alpaca live brokerage is restricted by jurisdiction and KYC. The Thai SEC licenses digital-asset exchanges and brokers; running a personal paper bot requires no licence, operating a bot for others does. Verify each claim at build time and record the date in `docs/thailand.md`.

### Risk vocabulary

Sharpe, Sortino, Calmar, max drawdown, drawdown duration, exposure, turnover, hit rate, profit factor, volatility targeting, Kelly fraction (document, do not implement), value at risk (document only). Each gets a one-line definition and the formula used in `metrics.py`.

### Reading list for the agent (public, stable)

- Marcos López de Prado, Advances in Financial Machine Learning (purged CV, embargo, deflated Sharpe).
- Bailey and López de Prado, The Deflated Sharpe Ratio (2014).
- Ernest Chan, Quantitative Trading (practical backtesting pitfalls).
- CCXT manual, Alpaca API docs, `pandas_market_calendars` docs.
- Papers on momentum and mean reversion effects in crypto and equities, cited by title in `KNOWLEDGE_BASE.md` with a one-line takeaway each.

## 21. Glossary and open decisions

### Glossary

| Term | Meaning here |
| --- | --- |
| Bar | One OHLCV candle; `ts` is its open time in UTC |
| Target weight | Fraction of equity a strategy wants in a symbol, 0 to 1 |
| Cycle | One scheduled pass of the live loop at a bar close |
| Reconcile | Replace local state with the broker's positions and balances |
| Halt | Flatten everything and stop trading until resumed |
| Paper | A broker-simulated account with fake money and real prices |
| Sandbox or testnet | An exchange's separate fake-money environment |
| Walk-forward | Sequential train-then-test windows across time |
| Embargo | A gap after a test fold so labels cannot leak |
| Deflated Sharpe | Sharpe adjusted for how many things you tried |
| Regime | A labelled market state (trend or chop, high or low vol) |
| Universe | The list of symbols a strategy may trade |

### Decisions the agent makes alone (and records in BUILD\_LOG)

- Exact library versions, internal module boundaries, test naming, report layout details.
- Default parameter values for reference strategies, within the ranges in `docs/strategies.md`.
- Which CCXT exchange is the default sandbox, after checking which testnets are reachable and documented.

### Decisions for the owner (write to OWNER\_TODO and continue with the default)

- [ ] Confirm the name `kestrel` or supply another before milestone 1 tags anything. Default: `kestrel`.
- [ ] Which paper account to create first: Alpaca (one key, equities plus crypto) or a CCXT testnet. Default: build both adapters; the owner picks at run time.
- [ ] AI provider preference if any key will be used. Default: Anthropic first, OpenAI second, both optional.
- [ ] Hosting for the unattended run: home PC, or a Singapore VPS. Default: document all three supervision options; no deployment is performed.
- [ ] Whether `xs_rank` should ship in 0.1.0 or 0.2.0 if LightGBM wheels cause trouble on Windows. Default: ship behind the `[ml]` extra; if the extra fails CI on Windows, mark it experimental and release anyway.
- [ ] Universe lists: confirm the 20 crypto pairs and 30 US tickers. Default: top by market cap at build time, dated in the YAML.

### What this spec does not do

It does not predict that any strategy will make money. The reference strategies exist to exercise the system. The owner should expect the validation layer to mark most of them `caution` or `fail` on real data, and that is the correct outcome.
