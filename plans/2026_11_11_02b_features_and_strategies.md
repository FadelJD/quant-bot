# 02b · Features and reference strategies

Created 2026-11-11 · Wave 2 · Parallel with 02a, 02c to 02g · Needs 01 · Spec sections 7 and 8

## Goal

A causal feature library with declared lookbacks, and two reference strategies (`sma_cross`,
`boll_revert`) that behave exactly as documented. `xs_rank` is plan 03d.

## Owns

`src/kestrel/features/`, `src/kestrel/strategies/{__init__,base,sma_cross,boll_revert}.py`.

## Current state

Registry, 14 indicator families, cross-sectional ranks, a builder with an in-memory cache, the
`Strategy` base class, `BarContext`, registry decorator and both strategies exist and run.

## Work items

1. **Registry.**
   - Every family declares `n_params`, `lookback(params)`, `outputs(params)` (the exact column
     names it adds) and `description`. `outputs` lets the engine verify a strategy's `requires`
     before a run and lets `kestrel features list` (04a) print a table.
   - Reject duplicate registration and parameter counts that do not match, naming the feature.
   - `resolve()` orders dependencies; add a cycle check.
2. **Causality by construction.** Ban `shift(-n)`, `center=True`, `bfill` and full-series
   statistics inside `features/`. Add a guard function `assert_causal(fn, frame)` that recomputes a
   feature on a truncated frame and compares the overlap; wave 5 calls it for every family, and
   03a reuses it for the lookahead audit (I3).
3. **Indicator review against references.** For each family, write the formula in the docstring
   and check the implementation against it by hand on a 10-row frame (keep the worked numbers in
   the docstring so wave 5 can assert them): returns, log returns, rolling vol (annualised with
   the market's factor, not a hard-coded 365), SMA, EMA (`adjust=False`), MACD, ADX (Wilder), RSI
   (Wilder), Bollinger (population std), z-score, volume z-score, dollar volume, volatility
   tercile, trend regime.
4. **Annualisation.** `vol` reads `per_year` from `frame.attrs`; pandas drops `attrs` on some
   operations. Pass `per_year` explicitly through the builder instead.
5. **Builder cache.** Key is `(symbol, timeframe, spec hash, n_rows, last_ts)`. Add an explicit
   `clear()` and a size cap. Make incremental recompute cheap for the live loop: when only one new
   bar arrived, recompute the last `lookback + 1` rows and append.
6. **Cross-sectional features.** Computed per timestamp across symbols present at that timestamp.
   Symbols with NaN inputs are excluded from the rank, not ranked last.
7. **Strategy contract.**
   - `validate_targets`: unknown symbol, NaN, or positive sum above 1 raises `ConfigError`.
     Negative weights pass through for the engine to clamp and count.
   - `Strategy.requires` checked against the registry at construction, so a typo fails before the
     run starts.
   - `state()` and `load_state()` must round-trip through JSON for every strategy.
   - Document in the base class that `on_bar` must be deterministic given `ctx`.
8. **`sma_cross`.** Long when SMA(fast) > SMA(slow). Equal weight across longs, capped by
   `max_positions`. Ties and NaNs produce no position. Params: `fast` 2 to 200 (default 20),
   `slow` 3 to 400 (default 50), `fast < slow` validated.
9. **`boll_revert`.** Entry when close < lower band and RSI < threshold. Exit at the mid band or
   after `max_hold_bars`. Entries disabled when the volatility regime is high. Holding counters live
   in `state()`. Fix two details: the bar on which a position is entered must not count as a held
   bar, and an exit signal on the same bar as a fresh entry signal must resolve to flat.
10. **Schema output.** `Strategy.schema()` returns JSON schema with descriptions and ranges for
    every param, used by `kestrel strategies schema` and by `docs/strategies.md` (04c).
11. **Starter template.** `src/kestrel/_templates/strategy_template.py`: a 30-line commented
    strategy the owner can copy. Referenced by the README's "Writing a strategy" section.

## Done when

- Every feature family has a formula docstring with a worked 10-row example.
- `assert_causal` passes for every family when run from a scratch script.
- Both strategies run on the fixtures through the smoke gate and their `state()` round-trips.
- Static checks pass on owned files. Import contract "strategies never import execution or live" kept.

## Out of scope

`xs_rank`, portfolio optimisation, deep learning, tests.
