"""Walk-forward analysis: fit on window k, test on window k+1, repeat. Rolling or anchored."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import pandas as pd

RunFn = Callable[[pd.Timestamp, pd.Timestamp, dict[str, Any]], float]
"""``run(start, end, params) -> Sharpe`` for a backtest restricted to the window."""


@dataclass(frozen=True)
class Window:
    """One in-sample / out-of-sample pair."""

    is_start: pd.Timestamp
    is_end: pd.Timestamp
    oos_start: pd.Timestamp
    oos_end: pd.Timestamp


def walk_forward_windows(index: Sequence[pd.Timestamp], n_windows: int, mode: str = "rolling") -> list[Window]:
    """Tile ``index`` into ``n_windows`` out-of-sample windows that do not overlap.

    The period is split into ``n_windows + 1`` equal slices. Window ``k`` tests on slice
    ``k+1``; rolling mode trains on slice ``k``, anchored mode trains on slices ``0..k``.
    """
    n = len(index)
    if n_windows < 1 or n < 2 * (n_windows + 1):
        return []
    slice_len = n // (n_windows + 1)
    out: list[Window] = []
    for k in range(n_windows):
        is_lo = 0 if mode == "anchored" else k * slice_len
        is_hi = (k + 1) * slice_len - 1
        oos_lo = (k + 1) * slice_len
        oos_hi = (k + 2) * slice_len - 1 if k < n_windows - 1 else n - 1
        out.append(Window(index[is_lo], index[is_hi], index[oos_lo], index[oos_hi]))
    return out


@dataclass
class WalkForwardResult:
    """Per-window results and the summary statistics used by the verdict."""

    windows: list[dict[str, Any]]
    is_sharpe_mean: float
    oos_sharpe_mean: float
    oos_is_ratio: float
    fraction_positive: float

    def to_dict(self) -> dict[str, Any]:
        """Plain dict for JSON."""
        return self.__dict__.copy()


def walk_forward(
    run: RunFn,
    index: Sequence[pd.Timestamp],
    *,
    n_windows: int = 6,
    mode: str = "rolling",
    params: dict[str, Any] | None = None,
    grid: list[dict[str, Any]] | None = None,
) -> WalkForwardResult:
    """Run walk-forward analysis.

    For each window, if a ``grid`` is given the params with the best in-sample Sharpe are chosen
    (tuning); otherwise ``params`` are used as-is. The chosen params are then evaluated out of
    sample. Returns the OOS Sharpe per window, the OOS/IS ratio of means, and the fraction of
    windows with positive OOS Sharpe.
    """
    base = params or {}
    rows: list[dict[str, Any]] = []
    for w in walk_forward_windows(index, n_windows, mode):
        best_params, best_is = base, run(w.is_start, w.is_end, base)
        for candidate in grid or []:
            s = run(w.is_start, w.is_end, candidate)
            if s > best_is:
                best_params, best_is = candidate, s
        oos = run(w.oos_start, w.oos_end, best_params)
        rows.append(
            {
                "is_start": w.is_start.isoformat(),
                "is_end": w.is_end.isoformat(),
                "oos_start": w.oos_start.isoformat(),
                "oos_end": w.oos_end.isoformat(),
                "params": best_params,
                "is_sharpe": float(best_is),
                "oos_sharpe": float(oos),
            }
        )
    if not rows:
        return WalkForwardResult([], 0.0, 0.0, 0.0, 0.0)
    is_mean = sum(r["is_sharpe"] for r in rows) / len(rows)
    oos_mean = sum(r["oos_sharpe"] for r in rows) / len(rows)
    ratio = oos_mean / is_mean if is_mean > 0 else (1.0 if oos_mean > 0 else 0.0)
    frac = sum(1 for r in rows if r["oos_sharpe"] > 0) / len(rows)
    return WalkForwardResult(rows, is_mean, oos_mean, ratio, frac)
