"""``boll_revert``: buy below the lower Bollinger band with low RSI; exit at mid band or after N bars."""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import Field

from kestrel.strategies.base import BarContext, Strategy, StrategyParams, register_strategy


class BollRevertParams(StrategyParams):
    """Parameters for :class:`BollRevert`."""

    window: int = Field(default=20, ge=5, le=200, description="Bollinger window")
    k: float = Field(default=2.0, gt=0, le=5, description="Band width in standard deviations")
    rsi_window: int = Field(default=14, ge=2, le=100)
    rsi_entry: float = Field(default=30.0, gt=0, lt=100, description="Enter when RSI is below this")
    max_hold_bars: int = Field(default=10, ge=1, le=200, description="Time-based exit")
    max_positions: int = Field(default=5, ge=1)
    weight_per_position: float = Field(default=0.2, gt=0, le=1)
    disable_in_high_vol: bool = Field(default=True, description="Skip entries when vol regime is high")
    vol_regime_window: int = Field(default=20, ge=5)
    vol_regime_lookback: int = Field(default=250, ge=20)


@register_strategy
class BollRevert(Strategy):
    """Mean reversion with a time-based exit and a volatility-regime filter."""

    name = "boll_revert"
    Params = BollRevertParams
    description = (
        "Enter long when close < lower band and RSI < threshold; exit at the mid band or after N bars. "
        "Entries are disabled in the high-volatility regime."
    )
    params: BollRevertParams
    _held: dict[str, int]

    def __init__(self, params: BollRevertParams, *, timeframe: str = "1d", universe: str = "") -> None:
        """Create the strategy with an empty holding book."""
        super().__init__(params, timeframe=timeframe, universe=universe)
        self._held = {}

    @property
    def requires(self) -> list[str]:
        """Bollinger bands, RSI, and the volatility regime flag."""
        p = self.params
        k = int(p.k) if float(p.k).is_integer() else p.k
        return [
            f"boll_{p.window}_{k}",
            f"rsi_{p.rsi_window}",
            f"vol_regime_{p.vol_regime_window}_{p.vol_regime_lookback}",
        ]

    def _cols(self) -> tuple[str, str, str, str]:
        p = self.params
        k = int(p.k) if float(p.k).is_integer() else p.k
        base = f"boll_{p.window}_{k}"
        return (
            f"{base}_lower",
            f"{base}_mid",
            f"rsi_{p.rsi_window}",
            f"vol_regime_{p.vol_regime_window}_{p.vol_regime_lookback}",
        )

    def on_bar(self, ctx: BarContext) -> dict[str, float]:
        """Manage exits first, then entries, within the position cap."""
        lower, mid, rsi, regime = self._cols()
        targets: dict[str, float] = {}
        # Exits for held names.
        for sym in list(self._held):
            if sym not in ctx.features:
                del self._held[sym]
                continue
            row = ctx.last(sym)
            self._held[sym] += 1
            exit_now = row["close"] >= row[mid] or self._held[sym] >= self.params.max_hold_bars
            if exit_now:
                del self._held[sym]
            else:
                targets[sym] = self.params.weight_per_position
        # Entries.
        for sym in sorted(ctx.features):
            if sym in self._held or len(self._held) >= self.params.max_positions:
                continue
            row = ctx.last(sym)
            vals = (row[lower], row[rsi])
            if any(v != v for v in vals):
                continue
            if self.params.disable_in_high_vol:
                r = row.get(regime, float("nan"))
                if r == r and r >= 2.0:
                    continue
            if row["close"] < row[lower] and row[rsi] < self.params.rsi_entry:
                self._held[sym] = 0
                targets[sym] = self.params.weight_per_position
        total = sum(targets.values())
        if total > 1.0:
            targets = {s: w / total for s, w in targets.items()}
        return targets

    def state(self) -> dict[str, Any]:
        """Holding book: symbol -> bars held."""
        return {"held": dict(self._held)}

    def load_state(self, s: dict[str, Any]) -> None:
        """Restore the holding book."""
        self._held = {str(k): int(v) for k, v in dict(s.get("held", {})).items()}
