"""Run the full validation suite for a config and produce a :class:`ValidationReport`."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from kestrel.backtest.engine import Backtester, BacktestResult
from kestrel.config import RunConfig
from kestrel.data.synthetic import resample_path
from kestrel.errors import ConfigError
from kestrel.logsetup import get_logger
from kestrel.reporting.metrics import sharpe
from kestrel.strategies.base import Strategy, build_strategy
from kestrel.validation.bootstrap import block_bootstrap_sharpe
from kestrel.validation.deflated_sharpe import deflated_sharpe
from kestrel.validation.monte_carlo import monte_carlo_drawdown
from kestrel.validation.sensitivity import parameter_sensitivity
from kestrel.validation.verdict import decide
from kestrel.validation.walk_forward import walk_forward

log = get_logger(__name__)

SCHEMA_VERSION = 1


@dataclass
class ValidationReport:
    """The verdict and every check behind it. Serialisable."""

    schema_version: int
    run_id: str
    strategy: str
    params: dict[str, Any]
    verdict: str
    reasons: list[str]
    checks: dict[str, Any]
    walk_forward: dict[str, Any]
    sensitivity: dict[str, Any]
    monte_carlo: dict[str, Any]
    bootstrap: dict[str, Any]
    deflated_sharpe: dict[str, Any]
    memorisation: dict[str, Any]
    generated_at: str = field(default_factory=lambda: datetime.now(tz=UTC).isoformat())

    def to_json(self) -> str:
        """Stable JSON."""
        return json.dumps(asdict(self), indent=2, sort_keys=True, default=_json_default)

    def save(self, path: Path) -> None:
        """Write the report to ``path``."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> ValidationReport:
        """Read a report written by :meth:`save`."""
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(**raw)


def _json_default(obj: object) -> object:
    if isinstance(obj, np.floating | np.integer):
        return obj.item()
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, pd.Timestamp | datetime):
        return obj.isoformat()
    return str(obj)


class _Factory:
    """Build strategies and run windowed backtests for the validation methods."""

    def __init__(self, cfg: RunConfig, frames: dict[str, pd.DataFrame], strategy_factory: Any | None) -> None:
        self.cfg = cfg
        self.frames = frames
        self._factory = strategy_factory

    def strategy(self, params: dict[str, Any]) -> Strategy:
        if self._factory is not None:
            return self._factory(params)  # type: ignore[no-any-return]
        return build_strategy(self.cfg.strategy.name, params, timeframe=self.cfg.timeframe, universe=self.cfg.universe)

    def run(self, start: pd.Timestamp, end: pd.Timestamp, params: dict[str, Any], frames: dict[str, pd.DataFrame] | None = None) -> BacktestResult | None:
        cfg = self.cfg.model_copy(deep=True)
        cfg.backtest.start = start.date()
        cfg.backtest.end = end.date()
        try:
            strat = self.strategy(params)
        except ConfigError:
            return None
        data = frames if frames is not None else self.frames
        try:
            return Backtester(cfg, strat, data, run_id="validation").run()
        except ConfigError:
            return None

    def sharpe(self, start: pd.Timestamp, end: pd.Timestamp, params: dict[str, Any]) -> float:
        res = self.run(start, end, params)
        return float(res.metrics["sharpe"]) if res is not None else 0.0


def run_validation(
    cfg: RunConfig,
    frames: dict[str, pd.DataFrame],
    *,
    result: BacktestResult | None = None,
    strategy_factory: Any | None = None,
    n_trials: int | None = None,
) -> ValidationReport:
    """Run every validation method and decide the verdict.

    Args:
        cfg: Run config (its ``validation`` section holds the thresholds).
        frames: Symbol -> OHLCV frames for the full period.
        result: An existing full-period backtest result to reuse; run if omitted.
        strategy_factory: Optional ``params -> Strategy`` (used by tests to inject fixtures).
        n_trials: Number of variants tried, for the deflated Sharpe; overrides config.

    Returns:
        A :class:`ValidationReport`.
    """
    vcfg = cfg.validation
    factory = _Factory(cfg, frames, strategy_factory)
    params = dict(cfg.strategy.params)
    full = result or factory.run(pd.Timestamp(cfg.backtest.start_ts), pd.Timestamp(cfg.backtest.end_ts), params)
    if full is None:
        raise ConfigError("validation: the full-period backtest could not run")
    per_year = cfg.annualisation
    returns = full.returns.to_numpy(dtype=float)
    n_obs = len(returns)
    index = list(full.equity_curve.index)
    trials = n_trials or vcfg.n_trials or 1

    # 1. Walk-forward.
    wf = walk_forward(factory.sharpe, index, n_windows=vcfg.n_windows, mode=vcfg.walk_forward_mode, params=params)

    # 3. Deflated Sharpe (per-bar Sharpe).
    sr_bar = float(full.metrics["sharpe"]) / np.sqrt(per_year) if per_year > 0 else 0.0
    dsr = deflated_sharpe(sr_bar, n_trials=trials, n_obs=n_obs, skew=float(full.metrics["skew"]), kurt=float(full.metrics["kurtosis"]))

    # 4. Sensitivity.
    def _eval(p: dict[str, Any]) -> float | None:
        res = factory.run(pd.Timestamp(cfg.backtest.start_ts), pd.Timestamp(cfg.backtest.end_ts), p)
        return float(res.metrics["sharpe"]) if res is not None else None

    sens = parameter_sensitivity(_eval, params, step=vcfg.sensitivity_step, drop_threshold=vcfg.sensitivity_drop)

    # 5. Monte Carlo on trade order.
    sells = full.trades[full.trades["side"] == "sell"] if not full.trades.empty else full.trades
    pnl = sells["realised_pnl"].to_numpy(dtype=float) if len(sells) else np.empty(0)
    mc = monte_carlo_drawdown(pnl, initial_equity=cfg.backtest.initial_cash, n_resamples=vcfg.mc_resamples, ruin_drawdown=cfg.risk.max_drawdown, seed=cfg.backtest.seed)

    # 6. Block bootstrap on Sharpe.
    boot = block_bootstrap_sharpe(returns, per_year=per_year, block=vcfg.bootstrap_block, n_resamples=vcfg.bootstrap_resamples, seed=cfg.backtest.seed)

    # 7. Implausibility and memorisation (the overfit-fixture pattern).
    implausible, impl_reason = _implausible(full, vcfg)
    memo = _memorisation(factory, full, params, cfg)

    checks: dict[str, Any] = {
        "n_trades": int(full.metrics["n_trades"]),
        "sharpe": float(full.metrics["sharpe"]),
        "dsr": dsr["dsr"],
        "n_windows": len(wf.windows),
        "oos_is_ratio": wf.oos_is_ratio,
        "fraction_positive_oos": wf.fraction_positive,
        "sharp_peak": sens["sharp_peak"],
        "bootstrap_ci_low": boot["ci_low"],
        "bootstrap_n_obs": boot["n_obs"],
        "probability_of_ruin": mc["probability_of_ruin"],
        "implausible": implausible,
        "implausible_reason": impl_reason,
        "memorisation": memo["flagged"],
        "memorisation_reason": memo["reason"],
    }
    verdict, reasons = decide(checks, vcfg)
    log.info("validation_verdict", verdict=verdict, reasons=reasons, run_id=full.run_id)
    return ValidationReport(
        schema_version=SCHEMA_VERSION,
        run_id=full.run_id,
        strategy=full.strategy,
        params=params,
        verdict=verdict,
        reasons=reasons,
        checks=checks,
        walk_forward=wf.to_dict(),
        sensitivity=sens,
        monte_carlo=mc,
        bootstrap=boot,
        deflated_sharpe=dsr,
        memorisation=memo,
    )


def _implausible(full: BacktestResult, vcfg: Any) -> tuple[bool, str]:
    s = float(full.metrics["sharpe"])
    hit = float(full.metrics["hit_rate"])
    n = int(full.metrics["n_round_trips"])
    if s > vcfg.max_plausible_sharpe:
        return True, f"annualised Sharpe {s:.1f} exceeds the plausibility ceiling {vcfg.max_plausible_sharpe:.1f}; lookahead or memorisation suspected"
    if n >= 30 and hit > vcfg.max_plausible_hit_rate:
        return True, f"hit rate {hit:.0%} over {n} round trips exceeds {vcfg.max_plausible_hit_rate:.0%}; lookahead or memorisation suspected"
    return False, ""


def _memorisation(factory: _Factory, full: BacktestResult, params: dict[str, Any], cfg: RunConfig) -> dict[str, Any]:
    """Re-run on block-resampled price paths; a date-keyed edge vanishes, a structural one survives."""
    vcfg = cfg.validation
    base = float(full.metrics["sharpe"])
    if base <= 0 or vcfg.memorisation_resamples <= 0:
        return {"flagged": False, "reason": "", "original_sharpe": base, "resampled_sharpes": []}
    sharpes: list[float] = []
    for k in range(vcfg.memorisation_resamples):
        frames = {s: resample_path(f, seed=cfg.backtest.seed + 1000 + k, block=vcfg.bootstrap_block) for s, f in factory.frames.items()}
        res = factory.run(pd.Timestamp(cfg.backtest.start_ts), pd.Timestamp(cfg.backtest.end_ts), params, frames=frames)
        sharpes.append(float(res.metrics["sharpe"]) if res is not None else 0.0)
    median = float(np.median(sharpes))
    retained = median / base if base > 0 else 1.0
    flagged = bool(base > 1.0 and retained < vcfg.memorisation_retention)
    reason = (
        f"Sharpe falls from {base:.2f} to a median of {median:.2f} on resampled price paths ({retained:.0%} retained); the edge is tied to the calendar, not the price structure"
        if flagged
        else ""
    )
    return {"flagged": flagged, "reason": reason, "original_sharpe": base, "resampled_sharpes": sharpes, "retained": retained}


def sharpe_of(returns: np.ndarray, per_year: float) -> float:
    """Re-export for callers that only need the Sharpe helper."""
    return sharpe(returns, per_year)
