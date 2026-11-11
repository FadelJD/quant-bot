# 03d · ML strategy `xs_rank`

Created 2026-11-11 · Wave 3 · Parallel with 03a to 03c, 03e · Needs 02b, 02c · Spec section 8

## Goal

A cross-sectional LightGBM ranker that exercises the ML path honestly: strict past-only training,
an embargo equal to the label horizon, retraining on a cadence, persisted models, all behind the
optional `[ml]` extra.

## Owns

`src/kestrel/strategies/xs_rank.py` only. It calls `validation.purged_kfold` with the signature
frozen in plan 01 and does not edit that file (03a owns it in the same wave).

## Current state

The class exists with training, cadence and persistence. It has never been constructed.

## Work items

1. **Optional import.** Importing `kestrel.strategies` must work without LightGBM. Constructing
   `xs_rank` without it raises `ConfigError("install kestrel[ml]")`. `kestrel strategies list`
   shows it as "needs [ml]" when the extra is missing.
2. **Training set, with the indices written out in the docstring.** At decision bar `n-1` with
   horizon `h`: a sample at bar `i` has label `close[i+h] / close[i] - 1`. It is usable only when
   `i + h <= n - 1 - h`, so every label window ends at least `h` bars before the decision bar.
   Check the current slicing against this by hand on a constructed 100-bar case and keep the case
   in the docstring. Labels are ranked across symbols per timestamp.
3. **Features.** Momentum (5, 20, 60), volatility (20, 60), volume z-score, and cross-sectional
   ranks and z-scores of momentum and volatility. All come from the registry (02b); nothing is
   computed inside the strategy.
4. **Retraining cadence.** Every `retrain_every` bars (default 60). Between retrains the model is
   frozen. Rebalance every `rebalance_every` bars (default 5, weekly on daily bars). Hold top-k
   equal weight.
5. **Determinism.** `seed`, `deterministic=True`, `n_jobs=1`, `force_col_wise=True`. Same data,
   same seed, same booster text. Verify across two runs.
6. **Speed.** Training on the fixtures under 30 s for the whole backtest. Vectorise the training
   set assembly (one concatenated frame cached and extended, not rebuilt each retrain).
7. **Persistence.** One booster text file per fold under `artifacts/models/<run_id>/`, plus a
   small JSON with fold number, training window, embargo, feature list, sample count.
   `load_state` reloads the latest booster so a restarted live run does not start blind.
8. **Purged CV report.** Use `purged_kfold` to produce an out-of-fold rank IC (Spearman between
   predicted and realised rank) per fold. Expose it as `XsRank.diagnostics()`; 03c may show it.
   A mean IC near zero is the expected, honest result on synthetic data.
9. **Failure behaviour.** Too few samples: return no targets and log once. NaN features for a
   symbol: exclude that symbol from scoring.
10. **Windows.** LightGBM ships wheels for Windows; confirm the import works in CI's Windows job
    (04b). If it fails there, mark `xs_rank` experimental and record the owner decision.

## Done when

- A backtest of `xs_rank` on the fixtures completes in under 30 s from a scratch script.
- The embargo arithmetic is verified by a constructed case and written in the docstring.
- The core install without `[ml]` still passes the smoke gate.
- Model files and their JSON appear under `artifacts/models/`.

## Out of scope

Deep learning, hyperparameter search, feature selection, tests.
