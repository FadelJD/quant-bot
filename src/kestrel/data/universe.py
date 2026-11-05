"""Universe definitions: static symbol lists in YAML, dated, with the survivorship caveat."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from kestrel.errors import ConfigError


@dataclass(frozen=True)
class Universe:
    """A named list of symbols for one market."""

    name: str
    market: str
    as_of: str
    symbols: tuple[str, ...]
    note: str = ""


def load_universe(name: str, universe_dir: Path | str = "configs/universes") -> Universe:
    """Load ``<universe_dir>/<name>.yaml``.

    Args:
        name: Universe key, e.g. ``crypto_top20``.
        universe_dir: Directory of universe YAML files.

    Returns:
        The :class:`Universe`.

    Raises:
        ConfigError: If the file is missing or malformed.
    """
    path = Path(universe_dir) / f"{name}.yaml"
    if not path.exists():
        raise ConfigError(f"universe {name!r} not found at {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "symbols" not in raw or "market" not in raw:
        raise ConfigError(f"universe {path} must define 'market' and 'symbols'")
    symbols = tuple(str(s) for s in raw["symbols"])
    if len(set(symbols)) != len(symbols):
        raise ConfigError(f"universe {path} has duplicate symbols")
    return Universe(
        name=name,
        market=str(raw["market"]),
        as_of=str(raw.get("as_of", "")),
        symbols=symbols,
        note=str(raw.get("note", "")),
    )


def universe_from_symbols(name: str, market: str, symbols: list[str]) -> Universe:
    """Build an in-memory universe (tests and the synthetic data source)."""
    return Universe(name=name, market=market, as_of="", symbols=tuple(symbols))
