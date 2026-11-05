"""Purged k-fold cross-validation with embargo (López de Prado, AFML chapter 7)."""

from __future__ import annotations

import numpy as np


def purged_kfold(
    n_samples: int,
    n_splits: int,
    *,
    label_horizon: int,
    embargo: int | None = None,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Return ``(train_idx, test_idx)`` pairs with purging and embargo.

    Folds are contiguous in time. A training sample ``i`` whose label window
    ``[i, i + label_horizon]`` overlaps the test fold ``[t0, t1]`` is purged, and samples inside
    ``embargo`` bars after ``t1`` are dropped too.

    Args:
        n_samples: Number of ordered samples.
        n_splits: Number of folds.
        label_horizon: Bars each label looks ahead.
        embargo: Bars to skip after each test fold (defaults to ``label_horizon``).

    Returns:
        List of ``(train_idx, test_idx)`` arrays.
    """
    if n_splits < 2 or n_samples < n_splits:
        raise ValueError("need at least two folds and more samples than folds")
    emb = label_horizon if embargo is None else embargo
    idx = np.arange(n_samples)
    bounds = np.linspace(0, n_samples, n_splits + 1, dtype=int)
    out: list[tuple[np.ndarray, np.ndarray]] = []
    for k in range(n_splits):
        t0, t1 = bounds[k], bounds[k + 1] - 1
        test = idx[t0 : t1 + 1]
        label_end = idx + label_horizon
        overlaps = (label_end >= t0) & (idx <= t1)
        in_embargo = (idx > t1) & (idx <= t1 + emb)
        train = idx[~overlaps & ~in_embargo]
        out.append((train, test))
    return out
