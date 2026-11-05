"""``sma_cross``: long when SMA(fast) > SMA(slow), flat otherwise. Equal weight across longs."""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import Field, model_validator

from kestrel.strategies.base import BarContext, Strategy, StrategyParams, register_strategy


class SmaCrossParams(StrategyParams):
    """Parameters for :class:`SmaCross`."""

    fast: int = Field(default=20, ge=2, le=200, description="Fast SMA window in bars")
    slow: int = Field(default=50, ge=3, le=400, description="Slow SMA window in bars")
    max_positions: int = Field(default=20, ge=1, description="Cap on simultaneous longs")

    @model_validator(mode="after")
    def _fast_lt_slow(self) -> SmaCrossParams:
        if self.fast >= self.slow:
            raise ValueError(f"fast ({self.fast}) must be less than slow ({self.slow})")
        return self


@register_strategy
class SmaCross(Strategy):
    """Simplest possible end-to-end check: a per-symbol moving-average crossover."""

    name = "sma_cross"
    Params = SmaCrossParams
    description = "Long when SMA(fast) > SMA(slow), flat otherwise; equal weight across longs."
    params: SmaCrossParams

    @property
    def requires(self) -> list[str]:
        """Fast and slow SMAs."""
        return [f"sma_{self.params.fast}", f"sma_{self.params.slow}"]

    def warmup_bars(self) -> int:
        """One extra bar so the first decision has a prior state."""
        return 1

    def on_bar(self, ctx: BarContext) -> dict[str, float]:
        """Equal weight across symbols whose fast SMA is above the slow SMA."""
        longs: list[str] = []
        fast, slow = f"sma_{self.params.fast}", f"sma_{self.params.slow}"
        for sym in ctx.features:
            row = ctx.last(sym)
            f, s = row[fast], row[slow]
            if f == f and s == s and f > s:
                longs.append(sym)
        longs = sorted(longs)[: self.params.max_positions]
        if not longs:
            return {}
        w = 1.0 / len(longs)
        return dict.fromkeys(longs, w)

    def state(self) -> dict[str, Any]:
        """Stateless."""
        return {}
