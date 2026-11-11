# 00 · Master index and execution order

Created 2026-11-11 · Read this first · Not an executable lane

This folder turns the untested kestrel skeleton into the finished 0.1.0 described in the build
spec. Plans run in **waves**. Waves are sequential. Lanes inside a wave run **in parallel**, one
agent per lane. Every lane owns a disjoint set of files, so lanes in a wave never conflict.

## 1. Where the last agent stopped (measured on 2026-11-11, commit `0fdd2ca`)

| Check | Result |
| --- | --- |
| `uv sync --all-extras` (py3.12) | Resolves and installs. `uv.lock` not committed. |
| Import every module (69 files, 7 892 lines) | All import cleanly. |
| `kestrel --help` | Works; every command registered. |
| `lint-imports` | 3 contracts kept, 0 broken. |
| `ruff check` | 385 findings, 324 of them line length. 46 files unformatted. |
| `mypy --strict` | 34 errors in 11 files (17 in `reporting/metrics.py`). |
| `kestrel backtest` on `quickstart_synthetic.yaml` | Runs in 4 s, writes report and metrics. |
| `kestrel validate` on the same | Runs in 34 s, verdict `fail` (plausible for a random walk). |
| Tests | None exist. Only `tests/fixtures/overfit_strategy.py`. |
| Docs | Stubs. Spec is not in the repo. |

So the skeleton is a working draft, not a pile of syntax errors. The work left is hardening,
closing spec gaps, wiring, docs, tests, release.

## 2. Wave map

```
Wave 1  (1 agent, serial)    01  foundation_and_contract_freeze
                              |
Wave 2  (7 agents, parallel) 02a data_layer            02e execution_adapters_and_safety_gate
                             02b features_and_strategies   02f notify_and_telegram
                             02c backtest_engine_and_metrics   02g run_ledger_and_observability
                             02d risk_layer
                              |
Wave 3  (5 agents, parallel) 03a validation_layer      03d ml_strategy_xs_rank
                             03b live_loop_and_state_store   03e optional_integrations
                             03c html_report_and_exports
                              |
Wave 4  (3 agents, parallel) 04a cli_and_composition_root
                             04b packaging_deployment_and_ci
                             04c documentation_set
                              |
Wave 5  (up to 6 agents)     05  test_suite_and_quality_gates   (internal lanes A to F)
                              |
Wave 6  (1 agent, serial)    06  release_and_owner_handover
```

Dependencies that cross lanes inside a wave do not exist by construction: a wave-N lane only
consumes wave-(N-1) output plus the frozen contracts from plan 01.

## 3. File ownership matrix

A lane edits only what it owns. Everything else is read-only for that lane.

| Path | Owner |
| --- | --- |
| `pyproject.toml`, `uv.lock`, `.pre-commit-config.yaml`, `.secrets.baseline`, `.gitignore`, `scripts/smoke.py`, `docs/CONTRACTS.md`, `docs/SPEC.md` | 01, then 04b |
| `src/kestrel/{types,errors,clock,config}.py` and every `Protocol` | 01 (frozen after wave 1, see section 5) |
| `src/kestrel/data/`, `scripts/*fixtures*.py`, `_templates/universes/`, `tests/fixtures/` data files | 02a |
| `src/kestrel/features/`, `strategies/{__init__,base,sma_cross,boll_revert}.py`, `_templates/strategy_template.py` | 02b |
| `src/kestrel/backtest/`, `reporting/metrics.py`, `scripts/bench_backtest.py` | 02c |
| `src/kestrel/risk/` | 02d |
| `src/kestrel/execution/`, `scripts/contract_check.py` | 02e |
| `src/kestrel/notify/` | 02f |
| `src/kestrel/{logsetup,ledger}.py` | 02g |
| `src/kestrel/validation/` (signature of `purged_kfold` stays frozen in wave 3) | 03a |
| `src/kestrel/live/` | 03b |
| `src/kestrel/reporting/{html,export}.py`, `reporting/templates/`, `docs/img/report_*.png` | 03c |
| `src/kestrel/strategies/xs_rank.py` | 03d |
| `src/kestrel/integrations/` | 03e |
| `src/kestrel/{cli,wiring}.py`, `_templates/*.yaml` (run configs) | 04a |
| `Dockerfile`, `docker-compose.yml`, `deploy/`, `.github/` | 04b |
| `README.md`, `docs/*.md` (except CONTRACTS, SPEC, handoff), `docs/img/` | 04c |
| `tests/` | 05 |
| `CHANGELOG.md`, version bump, tag | 06 |

## 4. Rules every lane follows

1. **Spec section 1 still governs.** Paper and sandbox only. No secrets, no real keys, no live
   loop, no Telegram against a real token. Blocked or owner-level decision: record it and take the
   most conservative option.
2. **Branching.** `develop` is created in plan 01. Each lane works on `feat/<plan_id>` (for
   example `feat/02c_backtest_engine`) and opens a PR to `develop`. `main` is release-only.
3. **No shared append-only files during a wave.** Do not edit `docs/BUILD_LOG.md`,
   `docs/OWNER_TODO.md` or `PROGRESS.txt` in a lane. Write `docs/handoff/<plan_id>.md` instead
   (template in section 7). The wave gate merges them. This removes the classic parallel conflict.
4. **Dependencies.** All known dependencies are already in `pyproject.toml`. A lane that needs a
   new one lists it in its handoff note; the wave gate adds it and re-locks.
5. **Keep the smoke gate green.** `uv run python scripts/smoke.py` (built in plan 01) must pass on
   the lane branch before the PR. It is an infrastructure canary, not the test suite: no network,
   under 90 seconds.
6. **Quality bar on touched files.** `ruff check`, `ruff format --check`, `mypy --strict` and
   `lint-imports` clean for the files the lane owns. Google-style docstrings on every public
   function. AU/UK spelling. Timezone-aware UTC only.
7. **Do not write the test suite early.** Wave 5 owns `tests/`. A lane may add a short
   `if __name__ == "__main__"` demo or extend `scripts/smoke.py` through a handoff request, nothing
   more. This is the owner's instruction.
8. **Conventional commits**, one logical change each.

## 5. Contract freeze and how to change a frozen file

Plan 01 publishes `docs/CONTRACTS.md` with the exact signatures of: `MarketMeta`, `OrderIntent`,
`RunConfig` and its sections, `Clock`, `Strategy`/`BarContext`/`Fill`, `BacktestResult`,
`MarketAdapter` and its value types, `Notifier`/`Alert`, `BarSource`, `StateReader`, `UsageStore`,
`RunLedger`.

- **Additive change** (new optional field with a default, new method with a default body): the
  lane makes it, notes it under "Contract changes" in its handoff note.
- **Breaking change**: not allowed inside a wave. Record a request in the handoff note; the wave
  gate decides and applies it between waves.

## 6. Wave gate (run by one agent after every wave)

1. Merge the wave's PRs into `develop` (any order).
2. Apply dependency requests, `uv lock`, apply accepted contract change requests.
3. Run the smoke gate and the four static checks on the whole tree.
4. Append each `docs/handoff/<plan_id>.md` summary line to `docs/BUILD_LOG.md`; move "Owner
   decisions" entries into `docs/OWNER_TODO.md`; refresh `PROGRESS.txt`.
5. Flip the next wave's smoke steps from `pending` to `required` (see plan 01).
6. Tag `wave-N-done`.

## 7. Handoff note template (`docs/handoff/<plan_id>.md`)

```markdown
# <plan_id> handoff · <date>
Summary line (goes to BUILD_LOG):
Done:
Not done and why:
Defects closed (ids from the register):
Contract changes (additive made / breaking requested):
Dependency requests:
Owner decisions (dated, with the default taken):
Smoke gate: pass | fail (output tail)
```

## 8. Defect register (found by running the skeleton)

Each defect has one owning plan, or two where it spans a boundary and each closes its half.
Close it there and cite the id in the handoff note.

| Id | Defect | Plan |
| --- | --- | --- |
| D01 | `report.html` is 5.11 MB, over the 5 MB limit (full plotly.js embedded) | 03c |
| D02 | `sma_cross` makes 3 617 trades on 5 symbols over 4 years: every bar re-trades weight drift | 02d |
| D03 | Hit rate, average win/loss and profit factor are per sell fill, not per round trip | 02c |
| D04 | `--strategy X` keeps the config's params for another strategy and fails with `ConfigError` | 04a |
| D05 | `validate` takes 34 s for 5 symbols; engine does a label lookup per symbol per bar | 02c, 03a |
| D06 | `state show`, `halt`, `resume` create an empty database as a side effect | 03b |
| D07 | `RiskEngine.on_equity` start-of-day logic is wrong (`_sod_date` set before the `None` check; `_last_equity` via `hasattr`) | 02d |
| D08 | `kestrel init` copies configs through a repo-relative path; breaks from a wheel | 01 |
| D09 | `kestrel report --run-id` is a stub; curve and trades are not persisted per run | 03c |
| D10 | `kestrel data check` builds a synthetic `DataService` instead of reading the real config | 04a |
| D11 | `CcxtAdapter.get_quote` timezone handling is wrong; CCXT positions report zero average cost | 02e |
| D12 | `PtbTransport` calls `asyncio.run` per message; the bot is never started by `run` | 02f, 03b |
| D13 | A halt set from the CLI or Telegram only sets a flag; the loop never flattens on seeing it | 03b |
| D14 | 34 mypy errors, 385 ruff findings, 46 unformatted files | 01 |
| D15 | No `uv.lock`, no `.secrets.baseline` (CI secrets step would fail), no Dockerfile or compose | 01, 04b |
| D16 | Spec is not in the repo; README points at a path that does not exist | 01 |
| D17 | `run` uses a bare loop; APScheduler wiring and weekly report are unreachable | 03b |
| D18 | Backtest warm-up counts merged-calendar bars, not per-symbol history; late-listed symbols get NaN features silently | 02c |
| D19 | Slippage uses the fill bar's own volume, a mild lookahead | 02c |
| D20 | Equities gap detection is a weekend heuristic, not the exchange calendar | 02a |
| D21 | `LiveRunner` fetches bars from the adapter, bypassing the cached, validated data layer | 03b |
| D22 | `Decimal` at the execution boundary is partial; floats cross it in several places | 02e, 03b |
| D23 | Cache rewrites the whole file on every append; `empty_ohlcv` ignores its arguments | 02a |
| D24 | Reports are not byte-identical across runs (`generated_at` inside validation and HTML) | 03a, 03c |
| D25 | Mock paper run in `cli.run` builds a price feed that refetches bars on every quote | 04a |

## 9. Additions beyond the spec (owner to confirm; default is include)

Small, each inside one lane, each making the tool more honest or easier to operate.

| Id | Addition | Plan |
| --- | --- | --- |
| I1 | **Trial ledger**: every backtest and sweep is recorded per strategy; the deflated Sharpe reads the real number of variants tried instead of trusting a flag | 02g, 03a |
| I2 | **Cost stress check**: re-run at 2x fees and slippage; flag if the edge disappears | 03a |
| I3 | **Lookahead audit**: engine-level truncation invariance, runnable on any strategy | 03a |
| I4 | **Backtest/paper parity monitor**: each live cycle compares its targets with a shadow backtest step on the same bars | 03b |
| I5 | **Rehearsal mode**: `kestrel run --rehearse 7d` replays the loop on `SimClock` + `MockAdapter`, so the loop can be exercised without ever starting a real one | 03b, 04a |
| I6 | **Heartbeat and dead-man alert**: a heartbeat file plus an alert when no cycle completes in N bars | 03b |
| I7 | **Run provenance**: `run.json` with git SHA, config hash, data manifest hash, lock hash | 02g |
| I8 | **State schema versioning** and `kestrel state export` backup | 03b |
| I9 | **No-trade band**: skip rebalances smaller than a threshold (fixes D02 at the root) | 02d |
| I10 | **Cross-source data check**: compare closes between two public sources and report divergence | 02a |

## 10. Coverage check against the spec

| Spec section | Plans |
| --- | --- |
| 1 operating rules | 00, enforced in 02e, 03b |
| 3 owner environment, Thailand | 02a, 02e, 04c |
| 4 architecture, 5 layout and standards | 01, 04c |
| 6 data | 02a |
| 7 features, 8 strategies | 02b, 03d |
| 9 backtester and metrics | 02c |
| 10 validation | 03a |
| 11 risk | 02d |
| 12 adapters | 02e |
| 13 live loop | 03b |
| 14 CLI and Telegram | 02f, 04a |
| 15 config, secrets, integrations | 01, 03e |
| 16 logging, reports, alerts | 02g, 03c, 02f |
| 17 testing and CI | 05, 04b |
| 18 milestones, 19 README, 20 knowledge base, 21 decisions | 04c, 06 |
