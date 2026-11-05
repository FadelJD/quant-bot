# 🦅 kestrel

Backtest, validate, and paper-trade strategies across crypto and US equities, and find out when your backtest is lying.

> 🧪 Paper trading only. No live-money mode exists; adapters refuse non-paper endpoints.
> ⚖️ Nothing here is financial advice.

## 🚦 Status for the next developer

| | |
|---|---|
| 📍 Branch | `claude/new-session-u3eief` (owner: create `develop` from it) |
| 📄 Spec | `docs/kestrel spec` is the uploaded build spec; code follows its section numbers |
| ✅ Written | Every module in `src/kestrel/` (milestones 1 to 12 as code) |
| ❌ Executed | Nothing. No `uv sync`, no import check, no lint, no mypy, no pytest |
| 🧾 Detail | `PROGRESS.txt`, `docs/BUILD_LOG.md`, `docs/OWNER_TODO.md` |

## 🛑 Where it stopped

The owner halted the session mid-build, before verification. Treat `src/` as a first draft that has never been imported. Known risks to hit first:

- 🐼 Written against pandas 3.x (copy-on-write, `ME` resample alias); pinned `>=2.2,<4`.
- 🔗 `import-linter` contracts in `pyproject.toml` may need loosening (`risk/` imports nothing from `execution/`, but `live/` and `notify/` do).
- 🕒 `kestrel/data/calendar.py` NYSE path uses `pandas_market_calendars`; untested.
- 🧠 `strategies/xs_rank.py` needs the `[ml]` extra (LightGBM).
- 🌐 Market-data hosts were unreachable from the build container, so no parquet fixtures exist yet.

## ▶️ Where to continue

1. 📦 `uv sync --all-extras` then `uv run python -c "import kestrel.cli"` and fix import errors.
2. 🧹 `uv run ruff check . && uv run ruff format . && uv run mypy --strict && uv run lint-imports`.
3. 🧪 Write `tests/` per spec section 17. Priorities: backtest 5-bar hand scenario, feature no-lookahead, risk property test, endpoint allowlist, 7-day `SimClock` + `MockAdapter` live run, overfit fixture must `fail`.
4. 📊 Fixtures: `uv run python scripts/make_fixtures.py` (synthetic) now; `scripts/fetch_fixtures.py` on a machine with network.
5. 🏃 Smoke run: `uv run kestrel backtest --config configs/quickstart_synthetic.yaml` then `uv run kestrel validate --config configs/quickstart_synthetic.yaml`.
6. 📚 Fill `docs/` stubs (ARCHITECTURE, KNOWLEDGE_BASE, strategies, runbook, thailand, integrations) and `uv.lock`, then tag `0.1.0`.

## 🗺️ Map

```
src/kestrel/
  cli.py            🖥️  typer app: init doctor data backtest validate sweep run halt resume state strategies
  config.py         ⚙️  RunConfig (YAML) + Secrets (env only, SecretStr)
  clock.py          🕰️  RealClock / SimClock
  data/             💾  fetchers, parquet cache + manifest, schema validation, synthetic, calendar
  features/         📐  registry with lookbacks, causal indicators, cross-sectional
  strategies/       🎯  sma_cross, boll_revert, xs_rank
  backtest/         🔁  next-open fills, slippage, fees, participation cap, portfolio
  risk/             🛡️  sizing, limits, halts (daily loss, drawdown, error streak, stale data)
  validation/       🔍  walk-forward, purged CV, deflated Sharpe, sensitivity, Monte Carlo, bootstrap, verdict
  execution/        🔌  paper-only safety gate, MockAdapter, CcxtAdapter (sandbox), AlpacaAdapter (paper)
  live/             🚀  SQLite state store, lock, reconciler, kill switch, LiveRunner, scheduler
  reporting/        📈  metrics, metrics.json, HTML report (Jinja2 + Plotly)
  notify/           📲  null / console / Telegram with injected transport
  integrations/     🤖  optional LLM narrative, news headlines
configs/            📝  backtest_*, paper_*, quickstart_synthetic, universes/
scripts/            🧰  make_fixtures.py, fetch_fixtures.py
tests/fixtures/     🪤  overfit_strategy.py (must fail validation)
```

## 🧭 Design decisions already made

- 💧 Slippage: `min(cap, base_bps/1e4 + impact_k * notional / bar_dollar_volume)`.
- 🧯 Backtests record risk breaches as events; `--enforce-halts` makes them flatten like live.
- 🕵️ "Overfit pattern" = implausibility ceiling (Sharpe > 5 or hit rate > 90%) plus a memorisation test on block-resampled price paths.
- 🔑 Order ids: `kst-{strategy}-{symbol}-{bar_ts}-{n}`; adapters de-duplicate on them.

## 📜 Licence

MIT.
