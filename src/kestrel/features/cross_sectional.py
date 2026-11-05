"""Cross-sectional features: per-timestamp rank and z-score across the universe.

These are computed over a dict of per-symbol frames after the per-symbol features exist. They
are causal because each timestamp only looks at the same timestamp across symbols.
"""

from __future__ import annotations

import pandas as pd


def add_cross_sectional(frames: dict[str, pd.DataFrame], columns: list[str]) -> dict[str, pd.DataFrame]:
    """Add ``xs_rank_<col>`` (percentile rank) and ``xs_z_<col>`` (z-score) for each column.

    Args:
        frames: Per-symbol feature frames sharing a common index semantics.
        columns: Columns to rank across symbols at each timestamp.

    Returns:
        The same dict with the new columns added to each frame.
    """
    if not frames:
        return frames
    for col in columns:
        wide = pd.DataFrame({sym: f[col] for sym, f in frames.items() if col in f.columns})
        if wide.empty:
            continue
        rank = wide.rank(axis=1, pct=True)
        mean = wide.mean(axis=1)
        sd = wide.std(axis=1, ddof=0).replace(0, float("nan"))
        z = wide.sub(mean, axis=0).div(sd, axis=0)
        for sym, frame in frames.items():
            if sym in wide.columns:
                frame[f"xs_rank_{col}"] = rank[sym].reindex(frame.index)
                frame[f"xs_z_{col}"] = z[sym].reindex(frame.index)
    return frames
