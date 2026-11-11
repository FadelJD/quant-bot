# 05 · Test suite and quality gates

Created 2026-11-11 · Wave 5 · After wave 4 · Up to six agents on internal lanes A to F · Spec section 17

## Goal

Proof that the backtester does not lie and the live loop does not lose state. 85% line coverage
on `src/`, 100% on `backtest/`, `risk/` and `validation/`. Tests never touch the network.

## Why this is last

The owner asked for infrastructure first. By now contracts are frozen, behaviour is settled, and
the worked numbers each lane recorded in its handoff note become the assertions. Tests written
earlier would have been rewritten three times.

## Owns

`tests/`. Source fixes are allowed in any package **only** to correct a defect a test exposes;
each such fix is listed in the handoff note with the test that found it.

## Shared setup (one agent, first, half a day)

`tests/conftest.py`: `make_synthetic_ohlcv` fixture, fixture-data loader, `SimClock` factory,
`MockAdapter` factory with YAML scenarios under `tests/fixtures/scenarios/`, a temp project
directory fixture, a `RunConfig` builder, an environment scrubber that removes every `KESTREL_*`,
`APCA_*` and API-key variable. Markers: `unit` (default, under 10 s total), `integration` (under
2 min), `contract` (skipped unless `KESTREL_INTEGRATION=1`), `slow`, `benchmark`. A socket guard
that fails any test opening a network connection.

## Lanes (parallel after the shared setup; each owns its test folders)

**A · data and config.** Incremental fetch appends only the tail; second fetch makes zero calls;
validation rejects duplicates, non-monotonic index, bad OHLC, negative prices; gap detection for
both markets; forward-fill flag; manifest written with hashes; token bucket and 429 backoff with
an injected sleep; atomic write under a simulated crash; universes; YAML round-trip with defaults;
bad params give an error naming the field; secrets never appear in `repr` or logs.

**B · features and strategies.** Each feature against the hand-computed 10-row example from its
docstring; `assert_causal` for every family; registry dependency resolution and errors; each
strategy's weights on a crafted frame; weights in `[0, 1]`, sum at most 1; state round-trip;
`xs_rank` embargo on a constructed case, determinism, trains under 30 s, missing-extra message.

**C · backtest and metrics (100%).** Next-open fill; slippage and fee arithmetic by hand; partial
fill cap; lot and minimum-notional rounding; short clamp counted; sells before buys; equity
identity on every bar; warm-up per symbol; round-trip matching; every metric against a hand
calculation; determinism diff on saved results; **the 1-symbol 5-bar scenario with every number
asserted by hand**; `this_close` warns.

**D · risk and validation (100%).** Hypothesis property test, 500 examples: no post-risk order
breaches any limit for any input; no-trade band; vol-target arithmetic; daily-loss halt fires on
the same bar; drawdown halt; halt idempotent; state round-trip. Walk-forward windows tile without
overlap; purge and embargo on a constructed case; deflated Sharpe against the published worked
example; sensitivity flags a planted peak; Monte Carlo and bootstrap with fixed seeds; cost
stress; lookahead audit catches a deliberately leaky strategy; **overfit fixture fails**;
**random walk never passes across 20 seeds**; **planted drift passes**; verdict rule table.

**E · execution, live, notify, integrations.** Safety gate rejects every URL in
`KNOWN_LIVE_URLS` for both adapters and accepts the paper ones; client order id format and length
limits; mock scenarios (rejection, partial, timeout then success, stale quote); Decimal boundary.
Full 7-day `SimClock` run per strategy; crash injected between every pair of cycle steps leaves
consistent state; restart after missed bars reconciles and does not replay; lock blocks a second
instance; orphaned open order handled; external halt flattens; parity monitor fires on a planted
mismatch; dead-man alert. Telegram handlers with the recording transport; unknown chat ignored;
rate limiting; null notifier with no token. Absent key means absent feature; budget cap stops
calls; provider failure degrades with one warning; payload allowlist.

**F · CLI, reports, end to end.** Every command's `--help`; `--json` is valid JSON; exit codes
for each error class; `--strategy` override; `run` refuses without a verdict and with `fail`.
Report under 5 MB, contains the verdict banner, no external URLs, byte-identical twice; Playwright
screenshot at 375 px. End to end: `data fetch` (fixtures) → `backtest` → `validate` → `report`,
with `metrics.json` matching a committed golden file within 1e-9. Benchmark of the spec workload
under 60 s with `pytest-benchmark`. Wheel install smoke.

## Quality gates to switch on

1. Coverage: `--cov-fail-under=85` overall; a second step asserting 100% for `backtest/`,
   `risk/`, `validation/`. Exclusions only for provider-SDK glue that cannot run offline, each
   with a one-line reason.
2. `filterwarnings = error` for kestrel's own warnings and pandas `FutureWarning`.
3. `pytest -n auto` must pass with random ordering (`pytest-randomly`) to expose shared state.
4. Mutation spot-check (optional, time-boxed to one hour): run `mutmut` on `backtest/fills.py`
   and `risk/limits.py`; record the surviving mutants as follow-ups.
5. The contract suite is documented for the owner, never run by the agent.

## Done when

- `pytest -m "unit or integration"` is green on all four CI cells with both coverage gates on.
- The unit set runs under 10 s and the integration set under 2 minutes on CI.
- The three named validation tests and the 5-bar scenario exist and pass.
- Every source fix made here is listed with the test that exposed it.

## Out of scope

New features. Running anything against a real provider.
