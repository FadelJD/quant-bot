# 02c · Backtest engine and metrics

Created 2026-11-11 · Wave 2 · Parallel with 02a, 02b, 02d to 02g · Needs 01 · Spec section 9

## Goal

An event-driven backtester that is correct first and fast second: decisions at bar close, fills at
the next open, realistic costs, exact accounting, byte-identical output for identical input.

## Owns

`src/kestrel/backtest/`, `src/kestrel/reporting/metrics.py`.

## Current state

Engine, fill model, portfolio, metrics and a runner exist and produce a report. Measured: 4 s for
one strategy on 5 symbols over 4 years. Defects D03, D05 (engine half), D18, D19.

## Work items

1. **Loop order, stated once in the module docstring and followed exactly.** For bar `t`:
   fill orders queued at `t-1` at `open[t]`; mark to market at `close[t]`; risk monitoring;
   build `BarContext(t)`; strategy targets; risk converts to orders; queue for `t+1`.
   `fill_at: this_close` stays as a diagnostic with a logged warning and a banner flag in the result.
2. **Speed (D05).** Precompute, per symbol, numpy arrays for open, high, low, close, volume and an
   integer position per calendar bar (`-1` when the symbol has no bar). The loop indexes arrays;
   no `.loc` inside it. `BarContext.features[symbol]` becomes a zero-copy view
   (`frame.iloc[:i+1]`), built lazily only for symbols the strategy touches. Target: 3 strategies,
   20 symbols, 4 years daily under 60 s total; record the `cProfile` baseline in the handoff note.
3. **Warm-up (D18).** A symbol becomes tradable only once it has `lookback + warmup_bars` of its
   own history. Before that it is absent from `ctx.features`. Emit one `warmup` event per symbol.
4. **Fill model.**
   - Slippage fraction `min(cap, base_bps/1e4 + impact_k * notional / dollar_volume)`.
   - D19: use the **previous** bar's dollar volume for impact and the participation cap, so the
     fill uses nothing unknown at the open. Keep a config switch `participation_basis: prev_bar |
     fill_bar` defaulting to `prev_bar`; record the choice.
   - Partial fill at `max_participation`; remainder cancelled and logged, never carried.
   - Lot rounding down, minimum notional drop, both from `MarketMeta`. Add
     `load_market_meta(path)` for the `market_meta.json` format fixed in plan 01; fall back to
     per-market defaults when the file is absent (02a commits the file in the same wave).
   - Sells execute before buys within a bar so cash from exits funds entries; buys that still
     exceed cash are scaled down, never rejected silently (event `cash_cap`).
5. **Accounting invariants, enforced with cheap runtime assertions behind a `strict` flag (on by
   default in backtests):** `cash + sum(qty * close) == equity` to 1e-9; no negative quantity; no
   negative cash beyond 1e-6; fees and slippage totals equal the sums in the trade log.
6. **Round trips (D03).** Add `Portfolio.round_trips()`: FIFO match of buys to sells per symbol,
   giving entry and exit time, quantity, PnL net of both fees, bars held. Hit rate, average win and
   loss, profit factor and the Monte Carlo input (03a) all use round trips. `n_trades` stays the
   fill count; add `n_round_trips`.
7. **Metrics.** Verify each formula against the docstring: CAGR, annualised volatility, Sharpe
   (rf 0), Sortino, max drawdown and duration, Calmar, turnover, exposure, fees as a share of gross
   PnL, skew, kurtosis, performance by regime. Annualisation factors: 365 crypto daily, 252
   equities daily, 8 760 crypto hourly, 1 638 equities hourly. Normalise inputs to `np.ndarray`
   once per function. Guard every division.
8. **Trade reasons.** `signal` for a new or closed position, `rebalance` for a weight adjustment
   on an existing one, `risk_exit` from the risk layer, `eod_flat` reserved.
9. **Determinism.** No wall-clock values in `BacktestResult`. Sorted symbol iteration everywhere.
   Seeds flow from `backtest.seed` only. Running twice must give identical `metrics` dicts.
10. **Result persistence hook.** `BacktestResult.save(dir)` writes `equity.parquet`,
    `trades.parquet`, `events.jsonl` and `result.json`; `BacktestResult.load(dir)` restores it.
    This is what makes `kestrel report --run-id` real (03c closes D09 on top of it).
11. **Windowed re-runs.** `Backtester.run(start=None, end=None)` reuses the already-built feature
    frames and arrays, so walk-forward and sensitivity (03a) do not rebuild features per window.
12. **Benchmarks as a script, not a test.** `scripts/bench_backtest.py` prints wall time for the
    spec's target workload on synthetic data. Wave 5 wraps it with `pytest-benchmark`.

## Done when

- The spec workload runs under 60 s on this machine; the number is in the handoff note.
- Strict accounting assertions never fire on the three smoke backtests.
- Two identical runs produce identical `result.json`.
- `BacktestResult.save` and `load` round-trip.
- D03, D18, D19 closed; D05 engine half closed. Static checks pass on owned files.

## Out of scope

The no-trade band (02d owns it; the engine just executes the orders it is given). HTML. Tests.
