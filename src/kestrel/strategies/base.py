"""The Strategy contract, BarContext, and the strategy registry.

A strategy never touches orders, balances, or the clock; the engine builds a :class:`BarContext`
at each bar close and asks for target weights in ``[0, 1]`` per symbol.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar

import pandas as pd
from pydantic import BaseModel, ConfigDict, ValidationError

from kestrel.errors import ConfigError


@dataclass(frozen=True)
class PositionView:
    """Read-only view of one position."""

    symbol: str
    qty: float
    avg_cost: float
    market_value: float


@dataclass(frozen=True)
class Fill:
    """A completed (possibly partial) fill, passed to ``Strategy.on_fill``."""

    ts: datetime
    symbol: str
    side: str
    qty: float
    price: float
    fee: float
    reason: str


@dataclass(frozen=True)
class BarContext:
    """Everything a strategy may see at one bar close. Nothing from the future.

    ``features[symbol]`` is that symbol's feature frame up to and including ``ts``; a test
    asserts the last index equals ``ts``.
    """

    ts: datetime
    features: Mapping[str, pd.DataFrame]
    positions: Mapping[str, PositionView]
    cash: float
    equity: float
    regimes: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    bar_index: int = 0

    def last(self, symbol: str) -> pd.Series:
        """Return the most recent feature row for ``symbol``."""
        return self.features[symbol].iloc[-1]

    def weight(self, symbol: str) -> float:
        """Current weight of ``symbol`` in equity."""
        if self.equity <= 0:
            return 0.0
        pos = self.positions.get(symbol)
        return pos.market_value / self.equity if pos else 0.0


class StrategyParams(BaseModel):
    """Base for strategy parameter models; unknown keys are errors."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Strategy:
    """Base class for strategies. Subclasses set ``name``, ``Params``, ``requires`` and ``on_bar``."""

    name: ClassVar[str] = "base"
    Params: ClassVar[type[StrategyParams]] = StrategyParams
    description: ClassVar[str] = ""
    cross_sectional: ClassVar[tuple[str, ...]] = ()

    def __init__(self, params: StrategyParams, *, timeframe: str = "1d", universe: str = "") -> None:
        """Create a strategy with validated params."""
        self.params = params
        self.timeframe = timeframe
        self.universe = universe

    @property
    def requires(self) -> list[str]:
        """Feature names from the registry the strategy needs."""
        return []

    def warmup_bars(self) -> int:
        """Bars of history needed before the first decision (engine adds feature lookback)."""
        return 0

    def on_bar(self, ctx: BarContext) -> dict[str, float]:
        """Return target weight per symbol in ``[0, 1]``; omitted symbols mean 0."""
        raise NotImplementedError

    def on_fill(self, fill: Fill) -> None:
        """Optional hook; default no-op."""
        return None

    def state(self) -> dict[str, Any]:
        """Serialisable state for restart."""
        return {}

    def load_state(self, s: dict[str, Any]) -> None:
        """Restore state from :meth:`state`."""
        return None

    @classmethod
    def schema(cls) -> dict[str, Any]:
        """JSON schema of the parameter model."""
        return cls.Params.model_json_schema()


STRATEGIES: dict[str, type[Strategy]] = {}


def register_strategy(cls: type[Strategy]) -> type[Strategy]:
    """Class decorator registering a strategy under ``cls.name``."""
    if cls.name in STRATEGIES:
        raise ConfigError(f"strategy {cls.name!r} registered twice")
    STRATEGIES[cls.name] = cls
    return cls


def build_strategy(
    name: str, params: Mapping[str, Any] | None = None, *, timeframe: str = "1d", universe: str = ""
) -> Strategy:
    """Instantiate a registered strategy with validated params.

    Raises:
        ConfigError: Unknown name or invalid params (message names the field).
    """
    if name not in STRATEGIES:
        raise ConfigError(f"unknown strategy {name!r}; available: {sorted(STRATEGIES)}")
    cls = STRATEGIES[name]
    try:
        p = cls.Params.model_validate(dict(params or {}))
    except ValidationError as exc:
        lines = [f"  {'.'.join(str(x) for x in e['loc']) or '<root>'}: {e['msg']}" for e in exc.errors()]
        raise ConfigError(f"invalid params for strategy {name!r}:\n" + "\n".join(lines)) from exc
    return cls(p, timeframe=timeframe, universe=universe)


def validate_targets(targets: Mapping[str, float], universe: tuple[str, ...] | list[str]) -> dict[str, float]:
    """Check strategy output: known symbols, finite values, sum at most 1 (+1e-9 tolerance).

    Negative weights are allowed through here so the engine can clamp and count them.
    """
    out: dict[str, float] = {}
    for sym, w in targets.items():
        if sym not in universe:
            raise ConfigError(f"strategy returned weight for symbol outside the universe: {sym!r}")
        if not isinstance(w, int | float) or w != w:
            raise ConfigError(f"strategy returned a non-numeric weight for {sym!r}: {w!r}")
        out[sym] = float(w)
    total = sum(max(w, 0.0) for w in out.values())
    if total > 1.0 + 1e-9:
        raise ConfigError(f"strategy target weights sum to {total:.4f} > 1")
    return out
