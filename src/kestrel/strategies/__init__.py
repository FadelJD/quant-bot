"""Strategy layer: classes that turn features into target weights, selected by name from config."""

from kestrel.strategies import boll_revert, sma_cross, xs_rank  # noqa: F401 - register
from kestrel.strategies.base import (
    STRATEGIES,
    BarContext,
    Fill,
    PositionView,
    Strategy,
    build_strategy,
    register_strategy,
)

__all__ = [
    "STRATEGIES",
    "BarContext",
    "Fill",
    "PositionView",
    "Strategy",
    "build_strategy",
    "register_strategy",
]
