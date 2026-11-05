"""Deliberately bad strategy: memorises the best in-sample days. Validation must flag it as fail."""

from __future__ import annotations

from typing import Any, ClassVar

import pandas as pd

from kestrel.strategies.base import BarContext, Strategy, StrategyParams


class OverfitParams(StrategyParams):
    """No real parameters; ``top_fraction`` controls how many days are memorised."""

    top_fraction: float = 0.3


class OverfitStrategy(Strategy):
    """Buys everything on the dates it memorised as profitable, flat otherwise."""

    name = "overfit_lookup"
    Params = OverfitParams
    description = "Test fixture: lookup table of memorised good days. Must fail validation."
    params: OverfitParams

    def __init__(self, params: OverfitParams, frames: dict[str, pd.DataFrame], **kw: Any) -> None:
        """Memorise the dates whose next-bar return is in the top fraction, per symbol."""
        super().__init__(params, **kw)
        self.good: dict[str, set[pd.Timestamp]] = {}
        for s, f in frames.items():
            nxt = f["open"].shift(-2) / f["open"].shift(-1) - 1.0
            cutoff = nxt.quantile(1 - params.top_fraction)
            self.good[s] = set(f.index[nxt > cutoff])

    @property
    def requires(self) -> list[str]:
        """Needs one cheap feature so warm-up is short."""
        return ["ret_1"]

    def on_bar(self, ctx: BarContext) -> dict[str, float]:
        """Go long the symbols whose current timestamp was memorised."""
        ts = pd.Timestamp(ctx.ts)
        longs = [s for s in ctx.features if ts in self.good.get(s, set())]
        return dict.fromkeys(longs, 1.0 / len(longs)) if longs else {}
