# 03a · Validation layer

Created 2026-11-11 · Wave 3 · Parallel with 03b to 03e · Needs 02b, 02c, 02g · Spec section 10

## Goal

The product's differentiator. Every backtest number ships with a verdict, the verdict is hard to
fool, and the reasons are readable by someone who has never heard of a deflated Sharpe.

## Owns

`src/kestrel/validation/`.

## Current state

All six spec methods, a memorisation check, an implausibility check, verdict rules and a runner
exist. Measured 34 s on 5 symbols because every window rebuilds features (D05), and the report
carries a wall-clock timestamp (D24).

## Work items

1. **Speed (D05).** Build one `Backtester` per parameter set and call its windowed `run(start,
   end)` (02c item 11). Budget for the full suite on the spec workload: under 3 minutes; quick
   mode (`--quick`: 3 windows, 200 resamples, no memorisation resamples beyond 2) under 30 s.
2. **Walk-forward.** `n_windows + 1` equal slices; OOS windows tile the period with no overlap;
   rolling and anchored. With a grid, tune on IS by Sharpe and evaluate the winner OOS. Report
   per-window IS and OOS Sharpe, the ratio of means, and the fraction of windows with positive OOS
   **return** (the code uses Sharpe sign today; the spec says return).
3. **Purged k-fold with embargo.** Contiguous folds; purge training samples whose label window
   overlaps the test fold; embargo of `label_horizon` bars after each fold. Used by 03d.
4. **Deflated Sharpe.** Per-bar Sharpe, skew, kurtosis, sample length, `n_trials`. `n_trials`
   comes from, in order: the CLI flag, the sweep grid size, **the trial ledger** (I1). The variance
   term uses `ledger.sharpe_variance` when at least 5 trials exist, else the estimator variance.
   Print which source was used. Check the implementation against the worked example in Bailey and
   López de Prado (2014) and put the numbers in the docstring.
5. **Parameter sensitivity.** Plus and minus 20% on up to three numeric params; integer params
   stay integers and distinct; invalid combinations are skipped, not failed. Flag when any valid
   neighbour loses more than 50% of the centre Sharpe. Return a grid shaped for a heatmap.
6. **Monte Carlo on trade order.** Input is round-trip PnL (02c item 6). 1 000 shuffles; report
   the 5th-percentile max drawdown and the probability of breaching `risk.max_drawdown`.
7. **Block bootstrap.** Block 20, 1 000 resamples, 95% interval on annualised Sharpe.
8. **Overfit pattern.** Two checks, both producing a plain reason:
   - Implausibility: annualised Sharpe above 5, or hit rate above 90% over at least 30 round trips.
   - Memorisation: re-run on block-resampled price paths; flag when the median Sharpe keeps less
     than 25% of the original. Works because a date-keyed edge dies when the path is scrambled.
9. **I2 cost stress.** Re-run with fees and slippage multiplied by
   `validation.cost_stress_multiplier` (default 2). `caution` when Sharpe halves; `fail` when it
   turns negative from a positive base.
10. **I3 lookahead audit.** For a sample of 20 bars, re-run the strategy with the feature frames
    truncated at that bar and assert the targets equal the full run's. Any difference is `fail`
    with the first differing timestamp. Cheap, and it catches the most common backtest lie.
11. **Verdict.** `fail` on: deflated Sharpe below 0.90, OOS/IS below 0.3, fewer than 30 trades,
    overfit pattern, lookahead audit, cost stress sign flip. `caution` on any marginal check.
    `pass` otherwise. Thresholds from `ValidationConfig`. Each reason is one sentence with the
    number and the threshold.
12. **Report object.** `ValidationReport` with `schema_version`, stable keys, no wall-clock field
    inside the hashed payload (D24: keep `generated_at` outside it). `save` and `load`.
13. **Gate helper.** `latest_verdict(strategy, market, reports_dir)` returns the newest report for
    the **same config fingerprint**, so `kestrel run` refuses a strategy whose last verdict is
    `fail` and cannot be fooled by an old pass with different params.
14. **Ledger write.** Record every validation and its verdict through `RunLedger`.

## Done when

- Full validation on the quickstart finishes in under 60 s; quick mode in under 15 s.
- The overfit fixture returns `fail`; a strong planted regime signal returns `pass`; the random
  walk returns `fail` or `caution`. Checked from a scratch script on fixed seeds, numbers recorded
  in the handoff note for wave 5 to assert.
- Two identical runs produce identical report payloads.
- D05 closed, D24 validation half closed. Static checks pass on owned files.

## Out of scope

HTML rendering of the results (03c). Combinatorial purged CV. Tests.
