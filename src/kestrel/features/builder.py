"""Build the feature frame for every symbol once per run, cached by ``(symbol, timeframe, spec hash)``."""

from __future__ import annotations

import hashlib

import pandas as pd

from kestrel.features import indicators  # noqa: F401 - registers the families
from kestrel.features.cross_sectional import add_cross_sectional
from kestrel.features.registry import lookback_of, parse_feature_name, resolve


def spec_hash(names: list[str] | tuple[str, ...]) -> str:
    """Stable short hash of a resolved feature list."""
    joined = "|".join(resolve(names))
    return hashlib.sha256(joined.encode()).hexdigest()[:12]


def build_features(
    frame: pd.DataFrame,
    requires: list[str] | tuple[str, ...],
    *,
    per_year: float = 365.0,
) -> pd.DataFrame:
    """Compute every required feature (and dependencies) on a copy of ``frame``.

    Args:
        frame: Canonical OHLCV frame.
        requires: Feature names such as ``["sma_20", "rsi_14"]``.
        per_year: Bars per year, used by volatility features for annualisation.

    Returns:
        A new frame with the feature columns appended. Rows inside the lookback are NaN.
    """
    out = frame.copy()
    out.attrs["per_year"] = per_year
    for name in resolve(requires):
        spec, params = parse_feature_name(name)
        out = spec.fn(out, params)
    return out


class FeatureBuilder:
    """Per-run cache of feature frames keyed by ``(symbol, timeframe, spec hash)``."""

    def __init__(self, per_year: float = 365.0) -> None:
        """Create an empty cache."""
        self.per_year = per_year
        self._cache: dict[tuple[str, str, str], pd.DataFrame] = {}
        self.hits = 0
        self.misses = 0

    def build(
        self,
        frames: dict[str, pd.DataFrame],
        requires: list[str] | tuple[str, ...],
        *,
        timeframe: str,
        cross_sectional: list[str] | None = None,
    ) -> dict[str, pd.DataFrame]:
        """Build (or fetch from cache) the feature frames for a universe.

        Args:
            frames: Per-symbol OHLCV frames.
            requires: Feature names.
            timeframe: Bar size (part of the cache key).
            cross_sectional: Columns to rank across the universe after per-symbol features.

        Returns:
            Per-symbol feature frames.
        """
        key_hash = spec_hash(requires) + ("+" + ",".join(cross_sectional) if cross_sectional else "")
        out: dict[str, pd.DataFrame] = {}
        missing: dict[str, pd.DataFrame] = {}
        for sym, frame in frames.items():
            key = (sym, timeframe, key_hash + f"@{len(frame)}:{frame.index[-1].value if len(frame) else 0}")
            if key in self._cache:
                self.hits += 1
                out[sym] = self._cache[key]
            else:
                self.misses += 1
                missing[sym] = frame
        if missing:
            built = {sym: build_features(f, requires, per_year=self.per_year) for sym, f in missing.items()}
            if cross_sectional:
                all_frames = {**{s: out[s].copy() for s in out}, **built}
                add_cross_sectional(all_frames, cross_sectional)
                built = {s: all_frames[s] for s in built}
                out = {s: all_frames[s] for s in out}
            for sym, f in built.items():
                frame = missing[sym]
                key = (sym, timeframe, key_hash + f"@{len(frame)}:{frame.index[-1].value if len(frame) else 0}")
                self._cache[key] = f
                out[sym] = f
        return out

    @staticmethod
    def warmup(requires: list[str] | tuple[str, ...]) -> int:
        """Bars needed before every required feature is non-NaN."""
        return lookback_of(requires)
