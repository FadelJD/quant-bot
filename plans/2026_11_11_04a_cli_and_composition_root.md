# 04a · CLI and composition root

Created 2026-11-11 · Wave 4 · Parallel with 04b, 04c · Needs all of waves 2 and 3 · Spec section 14

## Goal

One place that wires everything together, and a CLI where each command does one thing, prints one
result, and exits with a meaningful code.

## Owns

`src/kestrel/cli.py`, `src/kestrel/wiring.py` (new), `src/kestrel/_templates/*.yaml` (run configs).

## Current state

A 400-line `cli.py` builds objects inline. All spec commands are registered. Defects D04, D10, D25.

## Work items

1. **Composition root.** `wiring.py` holds the only construction code: `build_data_service`,
   `build_strategy`, `build_risk`, `build_adapter` (delegates to 02e's factory), `build_notifier`,
   `build_ledger`, `build_runner`, `build_narrator`. Each takes `RunConfig`, `Secrets`, `Clock`
   and returns a ready object. `cli.py` shrinks to argument parsing and printing. No global state.
2. **Config resolution (D04).** `--strategy X` selects `strategy.params_by_name[X]` or the
   strategy's defaults; it never reuses another strategy's params. Every command prints the
   resolved config with `--show-config`. Add `kestrel config show --config ...` and
   `kestrel config validate`.
3. **Commands, each with `--help` and an example, read commands with `--json`.**

   | Command | Notes |
   | --- | --- |
   | `init` | From packaged templates. Idempotent. Never overwrites an existing `.env`. |
   | `doctor` | Keys present (never values), adapter reachability to paper endpoints with a 5 s timeout, cache size, disk space, ML extra, lock and state health, AI token use and estimated spend. Reachability failures are reported, not fatal. |
   | `data fetch`, `data check [--against SRC]` | D10: use the real config and cache. `--against` runs the cross-source check (I10). |
   | `features list` | From the registry. |
   | `strategies list`, `strategies schema X`, `strategies describe X` | `describe` only when the AI integration is available. |
   | `backtest` | Writes `report.html`, `metrics.json`, `run.json`, and the saved result. Runs quick validation unless `--no-validate`. Records the run in the ledger. |
   | `validate [--quick] [--n-trials N]` | Full suite; writes `validation.json`; re-renders the report. |
   | `sweep --param a=lo:hi:step` | Parallel over a process pool (`--jobs`), every point recorded in the ledger, heatmap and CSV written, prints the grid size as the trial count. |
   | `trials [--strategy X]`, `trials reset` | Trial ledger view (I1). |
   | `report --run-id` | Regenerates from disk (03c). |
   | `explain --run-id` | Only when the AI integration is available. |
   | `run --config` | Refuses a `fail` verdict for the same config fingerprint unless `--i-understand-this-is-overfit`, which is logged at CRITICAL. Refuses when no verdict exists. Takes the lock. |
   | `run --rehearse 7d [--scenario file]` | I5: `SimClock` + `MockAdapter`, temp state, prints a summary. Safe for the agent to run. |
   | `halt --reason`, `resume --reason` | Through the state store; `resume` needs the reason typed back, same rule as Telegram. |
   | `state show`, `state export PATH` | Read-only open (D06 follow-through). |
4. **Mock paper run (D25).** `adapter.kind: mock` uses `BarPriceFeed` over frames loaded once.
5. **Exit codes.** 0 ok, 1 user or config error, 2 data error, 3 adapter error, 4 risk halt. One
   decorator maps `KestrelError` subclasses to codes and prints a one-line message, no traceback
   unless `--debug`.
6. **Output discipline.** Human output through `rich` to stdout; logs to stderr; `--json` prints
   exactly one JSON document and nothing else. Plain output when not a terminal. No colour when
   `NO_COLOR` is set. Works in Windows PowerShell and cmd (no characters outside the console's
   code page in default output).
7. **Startup time.** Lazy-import heavy modules inside commands so `kestrel --help` stays fast
   (target under 0.5 s).
8. **Configs.** Final `backtest_crypto`, `backtest_equities`, `paper_crypto`, `paper_equities`,
   `quickstart_synthetic`, each with `params_by_name` for all three strategies and short comments.
   Every one loads into `RunConfig` in the smoke gate.
9. **Flip the remaining smoke steps to required** with the wave gate: all three strategies,
   `validate --quick`, report size, 3-day rehearsal, safety gate.

## Done when

- Every command in the table runs from a fresh `kestrel init` folder on synthetic data.
- `kestrel run` without a validation verdict, and with a `fail` verdict, both refuse with exit 1.
- `kestrel run --rehearse 7d` prints a clean summary for each strategy.
- `cli.py` contains no object construction beyond calls into `wiring.py`.
- D04, D10, D25 closed. Smoke gate fully `required` and green.

## Out of scope

A TUI, shell completion beyond typer's default, tests.
