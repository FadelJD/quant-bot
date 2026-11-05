# Build log

- 2026-11-05: Session started on an empty repository. Python 3.11/3.12 available; `uv` present.
- 2026-11-05: Decision: pandas 3.x resolves by default; pinned `pandas>=2.2,<4` and wrote code to work on both.
- 2026-11-05: Decision: market-data hosts unreachable from the container; fixtures are synthetic (`scripts/make_fixtures.py`) until the owner runs `scripts/fetch_fixtures.py`.
- 2026-11-05: Decision: slippage formula interpreted in fractions, `slip = min(cap, base_bps/1e4 + impact_k * notional/bar_dollar_volume)`.
- 2026-11-05: Decision: in backtests risk breaches are recorded as events by default; `--enforce-halts` makes the backtester flatten and stop like the live loop.
- 2026-11-05: Decision: the "overfit fixture pattern" is implemented as two checks: an implausibility ceiling (annualised Sharpe > 5 or hit rate > 90%) and a memorisation test (Sharpe collapses on block-resampled price paths).
- 2026-11-05: Source skeleton for every module written (milestones 1 to 12 in code form). Owner asked to stop before any test, lint or type check ran. State recorded in `PROGRESS.txt`.
