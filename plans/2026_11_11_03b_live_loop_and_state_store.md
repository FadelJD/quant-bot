# 03b · Live paper loop and state store

Created 2026-11-11 · Wave 3 · Parallel with 03a, 03c to 03e · Needs 02a, 02d, 02e, 02f, 02g · Spec section 13

## Goal

A loop that survives crashes and reboots, never acts on state it has not reconciled with the
broker, halts itself on risk breaches, and can be rehearsed end to end without touching a broker.

## Owns

`src/kestrel/live/`.

## Current state

State store (SQLite, WAL), lock file, reconciler, kill switch, `LiveRunner` and an APScheduler
module exist. None has run. Defects D06, D13, D17, D21, D22 (runner half), D12 (wiring half).

## Hard rule

The agent never starts this loop against a real adapter, paper included. Everything here is
exercised with `SimClock` and `MockAdapter` only.

## Work items

1. **State store.**
   - I8: a `meta(schema_version)` table and an ordered list of migrations applied on open.
   - Open modes: `StateStore.open(path)` creates; `StateStore.open_readonly(path)` raises a
     readable error if the file is missing (D06). CLI read commands use the read-only mode.
   - One transaction per cycle keyed by `(run_id, bar_ts)`. A crash mid-cycle leaves the previous
     or the new state, never a mix. Use `BEGIN IMMEDIATE`, WAL, `synchronous=NORMAL`.
   - Store money as text decimals (D22) and convert at the edge.
   - Persist `RiskEngine.state()` and `Strategy.state()` in the cycle row.
   - `export(path)` writes a consistent copy with SQLite's backup API (I8).
2. **Lock file.** Exclusive create with the pid; stale-lock reclaim when the pid is dead. Pid
   liveness on Windows needs `OpenProcess` through `ctypes` or `psutil`; `os.kill(pid, 0)` is not
   reliable there. Release on normal exit and on `SIGTERM`.
3. **Cycle, exactly as the spec orders it.**
   1. Reconcile: positions, balance, open orders from the adapter; diff with local; trust the
      broker; `reconcile_drift` event; notify above 1% of equity.
   2. Halt flag. If set and positions exist, **flatten now** (D13): an external `/halt` or
      `kestrel halt` must not wait for anything. Then idle until the next cycle.
   3. Bars through `DataService` with `purpose="live"` (D21), incremental. Verify the newest bar
      is the expected one; apply the stale rule; notify after 3 skips.
   4. Features, `on_bar`, risk.
   5. Submit with idempotency keys; poll until terminal or timeout (60 s), then cancel and log.
      Sells before buys.
   6. Persist in one transaction.
   7. Cycle summary to the log; to Telegram only when something changed.
4. **Error policy.** `AdapterError` counts toward the streak and may halt; `DataError` skips the
   bar; anything else is caught once at the top, logged with `log_unhandled`, notified, re-raised
   so the supervisor restarts the process.
5. **Restart safety.** On start: read the last persisted bar; if more than one bar has passed,
   reconcile first and log `missed_bars`, never replay. Resolve open orders from the previous run
   by client id: record filled ones, cancel stale ones. Restore risk and strategy state.
6. **Scheduling (D17).** One code path: `run_forever()` computes the next bar close from the
   market calendar and sleeps through the `Clock`. APScheduler is used for the daily and weekly
   report jobs only, behind a thin `ReportScheduler` that is skipped under `SimClock`. Remove the
   duplicate cycle scheduling.
7. **Telegram wiring (D12).** The runner starts the bot (when configured) with halt and resume
   callbacks bound to the kill switch, and stops it on exit.
8. **Kill switch.** Cancel open orders, market-sell every position, write `HALTED` and the reason,
   notify. Idempotent across processes: the flag in the store is the guard, and flatten orders use
   deterministic client ids so a repeat cannot double-sell. `resume` needs the reason typed back.
9. **I6 heartbeat and dead-man.** Touch `live.heartbeat_path` every cycle with the last bar
   timestamp. A background check (same process, timer thread) raises a `dead_man` alert when no
   cycle has completed for `live.dead_man_bars` bars. Document the external version too: a
   supervisor health check that reads the heartbeat file's age.
10. **I4 parity monitor.** After computing targets, run one shadow step: build a `BarContext`
    from the same bars with the backtest path and compare targets. A mismatch logs
    `parity_drift` and notifies. This proves the claim that the same strategy code runs in both.
11. **I5 rehearsal.** `LiveRunner.rehearse(start, duration, frames, scenario)`: `SimClock`,
    `MockAdapter` fed by `BarPriceFeed`, a temp state store, `ConsoleNotifier`. Returns a summary
    (cycles, fills, halts, drift events, final equity). This is how the loop is demonstrated
    without breaking the hard rule. `kestrel run --rehearse 7d` (04a) calls it.
12. **Daily and weekly reports.** Daily at the configured local time: equity, day and week PnL,
    drawdown from peak, open positions, trades in the last 24 h, warnings. Weekly: regenerate the
    HTML report for the running strategy (through 03c's API) and send the file.
13. **Crash injection hook.** A test-only `fail_after_step` parameter that raises between steps,
    so wave 5 can prove transactional state without monkeypatching internals.

## Done when

- A 7-day rehearsal for `sma_cross` and `boll_revert` completes from a scratch script with zero
  unhandled exceptions and every local order matching the mock broker's record.
- Killing the rehearsal mid-cycle (hook) and restarting produces consistent state and no replay.
- A second instance on the same config is refused by the lock.
- An externally set halt flattens on the next cycle.
- D06, D13, D17, D21 closed; D12 and D22 runner halves closed.

## Out of scope

Real adapters at runtime. Process supervision files (04b). Tests.
