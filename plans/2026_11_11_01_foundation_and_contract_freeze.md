# 01 · Foundation and contract freeze

Created 2026-11-11 · Wave 1 · Serial, one agent · Blocks everything else

## Goal

Make the tree clean, reproducible and safe to split between seven parallel agents. Nothing in
this plan adds features. It removes every reason a later lane would need to touch a shared file.

## Owns

`pyproject.toml`, `uv.lock`, `.pre-commit-config.yaml`, `.secrets.baseline`, `.gitignore`,
`scripts/smoke.py`, `docs/CONTRACTS.md`, `docs/SPEC.md`, `docs/handoff/`,
`src/kestrel/{__init__,types,errors,clock,config}.py`, package data folder `src/kestrel/_templates/`.
For this wave only: formatting-only edits across all of `src/`.

## Current state

D08, D14, D15, D16 in the register. `uv.lock` has never been committed.

## Work items

1. **Branches.** Create `develop` from `claude/new-session-u3eief` and push it. All later lanes
   branch from `develop`.
2. **Spec in the repo.** Commit the build spec verbatim as `docs/SPEC.md`. Fix the README pointer.
3. **Lock and pin.** Commit `uv.lock`. Confirm `uv sync --all-extras` on Python 3.11 and 3.12.
   Confirm the core installs without `[ml]` (`uv sync` then `import kestrel.cli`).
4. **Mechanical cleanup (D14).** `ruff format .`, `ruff check --fix`, then hand-fix the rest.
   Decide line length once: keep 100 and wrap, do not raise the limit. For typer's `B008`, add a
   per-file ignore for `cli.py`. Rename `NaiveDatetimeWarning` only if N818 demands it, otherwise
   ignore N818 for that class.
5. **Types to zero.** Fix the 34 mypy errors without `Any` escapes where a real type exists.
   Hot spots: `reporting/metrics.py` (ndarray vs Series unions: normalise to `np.ndarray` at the
   top of each function), `data/calendar.py`, `data/fetchers.py`, `execution/alpaca_adapter.py`,
   `validation/monte_carlo.py`.
6. **Naive-datetime guard.** Ruff `DTZ` is on. Add a tiny script check in `scripts/smoke.py` that
   greps `src/` for `datetime.now()` and `utcnow()` without `tz` and fails on a hit.
7. **Package data (D08).** Move the default configs, universes and `.env.example` into
   `src/kestrel/_templates/` and ship them in the wheel. `configs/` at the repo root becomes a
   generated copy. Add `kestrel.config.template_dir()` using `importlib.resources`. `kestrel init`
   copies from there. Verify from a built wheel in a temp venv, not from the checkout.
8. **Secrets baseline (D15).** Generate `.secrets.baseline` with `detect-secrets scan`; audit it;
   confirm the CI command exits 0 and exits non-zero when a fake `sk-...` string is added.
9. **Config hardening.**
   - Per-strategy param blocks: allow `strategy.params_by_name: {sma_cross: {...}, boll_revert: {...}}`
     so a `--strategy` override picks the right block (prepares the D04 fix in 04a).
   - Add every field a later lane needs, as optional with a default, so no lane edits
     `config.py`: `risk.rebalance_band` (0.0 here; 02d sets the real default),
     `risk.backtest_halts` (`record | enforce`), `backtest.participation_basis`
     (`prev_bar | fill_bar`), `data.cross_check_source`, `live.heartbeat_path`,
     `live.dead_man_bars`, `validation.cost_stress_multiplier`, `validation.quick`,
     `integrations.llm.price_table`.
   - `RunConfig.fingerprint()` returning a stable SHA-256 of the canonical JSON.
   - `Secrets` must not read `.env` implicitly in tests: make the env file path injectable.
10. **Freeze the contracts.** Write `docs/CONTRACTS.md`: one section per contract listed in
    plan 00 section 5, with the exact signature copied from the code and one sentence of intent.
    Add two new protocol stubs that later lanes implement, so their names are fixed now:
    - `kestrel.ledger.RunLedger` protocol: `record_run(kind, strategy, params, config_fingerprint,
      metrics) -> str`, `trials_for(strategy) -> int`, `provenance() -> dict`.
    - `kestrel.live.state.StateReader` (already used by Telegram): confirm and document.
    - Cross-lane call signatures inside wave 3, fixed here so parallel lanes can call each other
      blind: `reporting.html.render_live_report(store, run_id, out_path, display_tz)`,
      `validation.latest_verdict(strategy, market, reports_dir, config_fingerprint)`,
      `validation.purged_kfold(...)` (unchanged), `LiveRunner.rehearse(...)`.
    - Shared helpers that two wave-2 lanes both need live in the foundation, not in either lane:
      `errors.raise_if_region_blocked(exc, provider)` (used by 02a and 02e) and the
      `market_meta.json` file format (written by 02a, read by 02c).
11. **Smoke gate.** `scripts/smoke.py`, standard library plus kestrel only, no network, exits
    non-zero on failure, prints one line per step. Steps carry a status `required` or `pending`.
    Initial steps:
    - required: import every module; `kestrel --help` and `--help` of every subcommand through
      typer's runner; naive-datetime grep; load every YAML in `_templates` into `RunConfig`;
      synthetic backtest of `sma_cross` finishes and writes both output files.
    - pending (flipped by later wave gates): backtest of all three strategies; `validate`; report
      under 5 MB; 3-day rehearsal run on `SimClock` + `MockAdapter`; safety gate rejects every
      known live URL; wheel build and install.
12. **Task shortcuts, cross-platform.** No Makefile (Windows is first-class). Document the five
    commands in `docs/CONTRACTS.md` under "Developer loop": sync, format, lint, type, smoke. Each
    shown for PowerShell and bash (they are identical with `uv run`).
13. **CI skeleton only.** Make `.github/workflows/ci.yml` run sync, lint, format check, mypy,
    import-linter, secrets scan and the smoke gate on the Ubuntu and Windows matrix. Leave the
    pytest step in place but allow "no tests collected" until wave 5 (04b finalises CI).
14. **Handoff folder.** Create `docs/handoff/` with the template from plan 00 and this plan's note.

## Done when

- `ruff check .`, `ruff format --check .`, `mypy --strict`, `lint-imports` all exit 0.
- `uv run python scripts/smoke.py` passes every `required` step on Ubuntu; CI is green on both OSes.
- A wheel built with `uv build`, installed in a fresh venv, runs `kestrel init` in an empty folder
  and produces `configs/` and `.env`.
- `docs/CONTRACTS.md` and `docs/SPEC.md` exist; `develop` is pushed.
- D08, D14, D15 (lock and baseline part), D16 closed.

## Out of scope

Behaviour changes in any package under `src/kestrel/<package>/`. Tests. Docs beyond CONTRACTS.
