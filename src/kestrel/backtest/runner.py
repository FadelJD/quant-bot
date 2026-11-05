"""Convenience: load data for a config, build the strategy, run, and return the result."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from kestrel.backtest.engine import Backtester, BacktestResult
from kestrel.config import RunConfig
from kestrel.data.service import DataService
from kestrel.data.universe import load_universe
from kestrel.strategies.base import Strategy, build_strategy


def run_id_for(cfg: RunConfig, strategy_name: str, now: datetime | None = None) -> str:
    """Deterministic run id: strategy, market, window, and a short config hash."""
    digest = hashlib.sha256(json.dumps(cfg.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()[:8]
    return f"{strategy_name}-{cfg.market}-{cfg.backtest.start:%Y%m%d}-{cfg.backtest.end:%Y%m%d}-{digest}"


def load_frames(cfg: RunConfig, *, root: Path | None = None, alpaca_key: tuple[str, str] | None = None) -> dict[str, object]:
    """Load bars for the config's universe through the data service."""
    base = root or Path.cwd()
    universe = load_universe(cfg.universe, base / cfg.universe_dir if not cfg.universe_dir.is_absolute() else cfg.universe_dir)
    service = DataService.from_config(cfg.data, cfg.market, root=base, alpaca_key=alpaca_key)
    return dict(service.get_universe_bars(universe.symbols, cfg.timeframe, cfg.backtest.start_ts, cfg.backtest.end_ts))


def run_backtest(
    cfg: RunConfig,
    *,
    strategy: Strategy | None = None,
    frames: dict[str, object] | None = None,
    root: Path | None = None,
    enforce_halts: bool = False,
    alpaca_key: tuple[str, str] | None = None,
) -> BacktestResult:
    """Run a backtest for ``cfg``; frames and strategy can be injected."""
    strat = strategy or build_strategy(cfg.strategy.name, cfg.strategy.params, timeframe=cfg.timeframe, universe=cfg.universe)
    data = frames if frames is not None else load_frames(cfg, root=root, alpaca_key=alpaca_key)
    bt = Backtester(cfg, strat, data, enforce_halts=enforce_halts, run_id=run_id_for(cfg, strat.name))  # type: ignore[arg-type]
    return bt.run()
