"""Feature registry: name, parameters, lookback, and the function that computes it.

A feature name is ``<family>`` or ``<family>_<param>[_<param>...]``, e.g. ``sma_20``,
``boll_20_2``. Each family declares how to parse its parameters and its lookback so the engine
can warm up correctly and the no-lookahead test can be run uniformly.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import pandas as pd

from kestrel.errors import ConfigError

FeatureFn = Callable[[pd.DataFrame, tuple[float, ...]], pd.DataFrame]


@dataclass(frozen=True)
class FeatureSpec:
    """One registered feature family."""

    family: str
    fn: FeatureFn
    n_params: int
    lookback: Callable[[tuple[float, ...]], int]
    defaults: tuple[float, ...] = ()
    depends: tuple[str, ...] = field(default_factory=tuple)
    description: str = ""

    def lookback_for(self, params: tuple[float, ...]) -> int:
        """Bars of history needed before the first valid value."""
        return int(self.lookback(params))


FEATURES: dict[str, FeatureSpec] = {}


def register(
    family: str,
    *,
    n_params: int,
    lookback: Callable[[tuple[float, ...]], int],
    defaults: tuple[float, ...] = (),
    depends: tuple[str, ...] = (),
    description: str = "",
) -> Callable[[FeatureFn], FeatureFn]:
    """Decorator registering a feature family under ``family``."""

    def deco(fn: FeatureFn) -> FeatureFn:
        if family in FEATURES:
            raise ConfigError(f"feature family {family!r} registered twice")
        FEATURES[family] = FeatureSpec(
            family=family,
            fn=fn,
            n_params=n_params,
            lookback=lookback,
            defaults=defaults,
            depends=depends,
            description=description,
        )
        return fn

    return deco


def parse_feature_name(name: str) -> tuple[FeatureSpec, tuple[float, ...]]:
    """Split ``sma_20`` into its spec and parameter tuple.

    Families may contain underscores (``ret_log``), so the longest registered prefix wins.

    Raises:
        ConfigError: If no family matches or the parameter count is wrong.
    """
    candidates = sorted(FEATURES, key=len, reverse=True)
    for family in candidates:
        if name == family or name.startswith(family + "_"):
            rest = name[len(family) :].lstrip("_")
            raw = [p for p in rest.split("_") if p] if rest else []
            spec = FEATURES[family]
            if not raw and spec.defaults:
                return spec, spec.defaults
            if len(raw) != spec.n_params:
                raise ConfigError(
                    f"feature {name!r}: family {family!r} takes {spec.n_params} parameter(s), got {len(raw)}"
                )
            try:
                params = tuple(float(p) for p in raw)
            except ValueError as exc:
                raise ConfigError(f"feature {name!r}: non-numeric parameter") from exc
            return spec, params
    raise ConfigError(f"unknown feature {name!r}; known families: {sorted(FEATURES)}")


def resolve(names: list[str] | tuple[str, ...]) -> list[str]:
    """Return ``names`` plus their dependencies in computation order, de-duplicated."""
    out: list[str] = []
    seen: set[str] = set()

    def visit(n: str) -> None:
        if n in seen:
            return
        spec, params = parse_feature_name(n)
        for dep in spec.depends:
            visit(_format(dep, params))
        seen.add(n)
        out.append(n)

    for n in names:
        visit(n)
    return out


def _format(template: str, params: tuple[float, ...]) -> str:
    """Fill ``{0}``-style placeholders in a dependency template with integer-looking params."""
    return template.format(*[_fmt(p) for p in params])


def _fmt(p: float) -> str:
    return str(int(p)) if float(p).is_integer() else str(p)


def lookback_of(names: list[str] | tuple[str, ...]) -> int:
    """Largest lookback across the resolved feature list."""
    worst = 0
    for n in resolve(names):
        spec, params = parse_feature_name(n)
        worst = max(worst, spec.lookback_for(params))
    return worst
