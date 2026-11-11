# 02g · Run ledger and observability

Created 2026-11-11 · Wave 2 · Parallel with 02a to 02f · Needs 01 · Spec sections 5, 16 · I1, I7

## Goal

Every run can be explained afterwards: what code, what config, what data, how many variants were
tried. Logs are structured, rotated, and free of secrets.

## Owns

`src/kestrel/logsetup.py`, `src/kestrel/ledger.py` (new).

## Current state

`logsetup.py` configures structlog with a redaction processor, console and a rotating JSON file.
No ledger exists. The `RunLedger` protocol name is fixed by plan 01.

## Work items

1. **Logging.**
   - JSON lines at `logs/kestrel-YYYY-MM-DD.jsonl`, rotated daily at UTC midnight, 30 files kept.
     The stdlib `TimedRotatingFileHandler` names files `base.suffix`; write a small handler that
     produces the spec's file name and works on Windows (no rename of an open file).
   - Pretty console only when attached to a terminal; JSON to stdout under a service manager.
   - Context fields on every event: `run_id`, `cycle_id`, `bar_ts`, `strategy`, `market`, bound
     with `structlog.contextvars`. Provide `bind_run(...)` and `bind_cycle(...)` helpers.
   - Levels as in spec section 16. `DEBUG` off by default.
2. **Redaction.** Two layers: key-name match (`key|secret|token|password`) masks the value;
   value scan masks `name=value` patterns and anything that looks like a key (long base64 or hex
   runs, `sk-` prefixes, Telegram bot token shape). `SecretStr` values render as `***`. Keep a
   list of safe field names that contain "key" but are not secrets (`config_key`, `client_order_id`
   is fine already) so useful fields are not masked.
3. **Run provenance (I7).** `provenance()` returns: kestrel version, git SHA and dirty flag when
   in a checkout (else `None`), Python version, platform, `uv.lock` hash when present, config
   fingerprint, data manifest fingerprint. Written as `run.json` beside every report and stored
   on the `runs` row of a live run.
4. **Trial ledger (I1).** A small SQLite file at `state/ledger.db` (separate from the live state
   store so research and trading never contend):
   - `runs(run_id, kind, strategy, params_json, params_hash, config_fingerprint,
     data_fingerprint, started_at, sharpe, verdict)`.
   - `record_run(...)` is called by every backtest, every sweep point and every validation.
   - `trials_for(strategy, data_fingerprint=None)` returns the number of **distinct param hashes**
     ever run for that strategy on that data. This is the honest `n_trials` for the deflated
     Sharpe: the tool counts, the owner does not have to remember.
   - `sharpe_variance(strategy)` returns the variance of per-bar Sharpe across recorded trials,
     which is the `V` term the deflated Sharpe needs.
   - `kestrel trials` and `kestrel trials reset --strategy X` are added by 04a.
5. **Timing helper.** `timed(event)` context manager logging duration; used by the engine and the
   live cycle so slow steps are visible without a profiler.
6. **Crash capture.** `log_unhandled(exc)` writes the traceback as one JSON event with the bound
   context, for the single top-level `except Exception` in the live runner.

## Done when

- A scratch script logs an event containing a fake token and a `SecretStr`; neither appears in the
  console or the file.
- Log files appear with the spec's name and rotate when the clock crosses midnight (simulated).
- `ledger.trials_for` returns 9 after a 3 x 3 sweep and still 9 after re-running the same sweep.
- `run.json` is produced by a backtest. Static checks pass on owned files.

## Out of scope

Calling the ledger from the engine or CLI (03a and 04a do that). Metrics dashboards. Tests.
