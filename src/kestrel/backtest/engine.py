"""The event-driven backtest engine.

Loop per bar ``t``: execute orders queued at ``t-1`` at bar ``t`` open, mark to market at bar
``t`` close, build :class:`BarContext`, ask the strategy for targets, pass them through risk,
queue the orders for ``t+1``. With ``fill_at: this_close`` (diagnostics only) the orders fill at
bar ``t`` close instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd

from kestrel.backtest.fills import FillModel
from kestrel.backtest.portfolio import Portfolio
from kestrel.config import RunConfig
from kestrel.errors import ConfigError
from kestrel.features.builder import FeatureBuilder
from kestrel.logsetup import get_logger
from kestrel.reporting.metrics import compute_metrics
from kestrel.risk.engine import RiskEngine
from kestrel.strategies.base import BarContext, Fill, Strategy, validate_targets
from kestrel.types import MarketMeta, OrderIntent, default_meta

log = get_logger(__name__)


@dataclass
class BacktestResult:
    """Everything a backtest produces, enough to render a report or feed validation."""

    run_id: str
    strategy: str
    params: dict[str, Any]
    equity_curve: pd.DataFrame
    trades: pd.DataFrame
    metrics: dict[str, Any]
    config: dict[str, Any]
    events: list[dict[str, Any]] = field(default_factory=list)
    regimes: pd.DataFrame | None = None
    features: dict[str, pd.DataFrame] = field(default_factory=dict)

    @property
    def returns(self) -> pd.Series:
        """Per-bar simple returns of equity."""
        return self.equity_curve["equity"].pct_change().dropna()


class Backtester:
    """Run one strategy over a universe of frames under one config."""

    def __init__(
        self,
        cfg: RunConfig,
        strategy: Strategy,
        frames: dict[str, pd.DataFrame],
        *,
        meta: dict[str, MarketMeta] | None = None,
        risk: RiskEngine | None = None,
        enforce_halts: bool = False,
        run_id: str = "backtest",
    ) -> None:
        """Create a backtester.

        Args:
            cfg: Run config.
            strategy: An instantiated strategy.
            frames: Symbol -> canonical OHLCV frame.
            meta: Symbol -> market metadata; defaults per market.
            risk: Risk engine; a fresh one from ``cfg.risk`` if omitted.
            enforce_halts: If True, risk halts flatten and stop trading as in a live run.
                If False (default for research), breaches are recorded as events only.
            run_id: Identifier used in the result.
        """
        if not frames:
            raise ConfigError("backtest needs at least one symbol with data")
        self.cfg = cfg
        self.strategy = strategy
        self.frames = frames
        self.meta = meta or {s: default_meta(s, cfg.market) for s in frames}
        self.risk = risk or RiskEngine(cfg.risk, initial_equity=cfg.backtest.initial_cash)
        self.enforce_halts = enforce_halts
        self.run_id = run_id
        self.fill_model = FillModel(cfg.backtest.fees, cfg.backtest.slippage, cfg.backtest.max_participation)
        self.symbols = tuple(sorted(frames))
        self.events: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ helpers

    def _regime_names(self) -> list[str]:
        return ["vol_regime_20_250", "trend_regime_200"]

    def _features(self) -> dict[str, pd.DataFrame]:
        builder = FeatureBuilder(per_year=self.cfg.annualisation)
        requires = [*self.strategy.requires, *self._regime_names()]
        xs = list(self.strategy.cross_sectional) or None
        return builder.build(self.frames, requires, timeframe=self.cfg.timeframe, cross_sectional=xs)

    def _warmup(self) -> int:
        base = FeatureBuilder.warmup(self.strategy.requires)
        return max(base, 1) + self.strategy.warmup_bars()

    # ------------------------------------------------------------------ main loop

    def run(self) -> BacktestResult:
        """Run the backtest and return the result."""
        cfg = self.cfg
        if cfg.backtest.fill_at == "this_close":
            log.warning("fill_at_this_close", note="diagnostics only; fills at the decision bar's close")
        feats = self._features()
        calendar = sorted(set().union(*(set(f.index) for f in feats.values())))
        calendar = [t for t in calendar if cfg.backtest.start_ts <= t <= cfg.backtest.end_ts]
        if not calendar:
            raise ConfigError("no bars inside the backtest window")
        warmup = self._warmup()
        portfolio = Portfolio(cfg.backtest.initial_cash)
        pending: list[tuple[datetime, OrderIntent]] = []
        regime_rows: list[dict[str, Any]] = []
        positions_at: dict[str, int] = {s: 0 for s in self.symbols}  # cursor into each frame
        index_pos = {s: {t: i for i, t in enumerate(f.index)} for s, f in feats.items()}

        for i, ts in enumerate(calendar):
            bars = {s: feats[s].loc[ts] for s in self.symbols if ts in index_pos[s]}
            if not bars:
                continue
            opens = {s: float(b["open"]) for s, b in bars.items()}
            closes = {s: float(b["close"]) for s, b in bars.items()}
            volumes = {s: float(b["volume"]) for s, b in bars.items()}

            # 1. Execute pending orders at this bar's open.
            if pending and cfg.backtest.fill_at == "next_open":
                self._execute(pending, ts, opens, volumes, portfolio)
                pending = []

            # 2. Mark to market at close.
            equity = portfolio.mark(ts, closes)
            breach = self.risk.on_equity(ts, equity)
            self.risk.record_equity(equity)
            if breach:
                self.events.append({"ts": ts.isoformat(), "type": "risk_breach", "reason": breach})
                if self.enforce_halts:
                    pending.extend((ts, o) for o in self.risk.flatten_orders(portfolio.qtys(), closes))
                    log.critical("halt", reason=breach, ts=ts.isoformat())
                else:
                    self.risk.clear_halt()

            if i < warmup:
                continue

            # 3. Context and strategy decision.
            views = {s: feats[s].iloc[: index_pos[s][ts] + 1] for s in bars}
            regimes = {s: {n: float(bars[s].get(n, float("nan"))) for n in self._regime_names()} for s in bars}
            regime_rows.append({"ts": ts, **{n: _majority(regimes, n) for n in self._regime_names()}})
            ctx = BarContext(
                ts=ts.to_pydatetime(),
                features=views,
                positions=portfolio.views(closes),
                cash=portfolio.cash,
                equity=equity,
                regimes=regimes,
                bar_index=i,
            )
            raw = self.strategy.on_bar(ctx)
            targets = validate_targets(raw, self.symbols)

            # 4. Risk: targets -> orders.
            vols = {s: float(bars[s].get("vol_20", float("nan"))) for s in bars}
            orders, report = self.risk.targets_to_orders(
                targets,
                equity=equity,
                positions=portfolio.qtys(),
                prices=closes,
                meta=self.meta,
                vols=vols,
                reason="signal",
            )
            if report.dropped_small or report.dropped_excess or report.scaled_gross:
                self.events.append({"ts": ts.isoformat(), "type": "limits", **report.__dict__})
            if cfg.backtest.fill_at == "this_close":
                self._execute([(ts, o) for o in orders], ts, closes, volumes, portfolio)
            else:
                pending.extend((ts, o) for o in orders)
            _ = positions_at

        curve = portfolio.equity_curve()
        trades = portfolio.trade_log()
        regimes_df = pd.DataFrame(regime_rows).set_index("ts") if regime_rows else None
        metrics = compute_metrics(
            curve,
            trades,
            per_year=cfg.annualisation,
            initial_cash=cfg.backtest.initial_cash,
            gross_buys=portfolio.gross_buys,
            gross_sells=portfolio.gross_sells,
            fees_paid=portfolio.fees_paid,
            slippage_paid=portfolio.slippage_paid,
            clamped_shorts=self.risk.clamped_shorts,
            regimes=regimes_df,
        )
        metrics["halts"] = [{"ts": t.isoformat(), "reason": r} for t, r in self.risk.breaches]
        return BacktestResult(
            run_id=self.run_id,
            strategy=self.strategy.name,
            params=self.strategy.params.model_dump(),
            equity_curve=curve,
            trades=trades,
            metrics=metrics,
            config=cfg.model_dump(mode="json"),
            events=self.events,
            regimes=regimes_df,
            features=feats,
        )

    def _execute(
        self,
        pending: list[tuple[datetime, OrderIntent]],
        ts: pd.Timestamp,
        prices: dict[str, float],
        volumes: dict[str, float],
        portfolio: Portfolio,
    ) -> None:
        for ts_signal, order in pending:
            if order.symbol not in prices:
                self.events.append({"ts": ts.isoformat(), "type": "no_bar", "symbol": order.symbol})
                continue
            meta = self.meta.get(order.symbol, default_meta(order.symbol, self.cfg.market))
            result = self.fill_model.fill(order, ref_price=prices[order.symbol], bar_volume=volumes[order.symbol], meta=meta)
            if result.cancelled_qty > 1e-12:
                self.events.append(
                    {"ts": ts.isoformat(), "type": "partial_or_cancel", "symbol": order.symbol, "cancelled_qty": result.cancelled_qty, "reason": result.reason}
                )
            if not result.filled:
                continue
            if order.side == "buy" and result.qty * result.price + result.fee > portfolio.cash + 1e-9:
                affordable = meta.round_qty(max(portfolio.cash - result.fee, 0.0) / result.price)
                if affordable <= 0 or affordable * result.price < meta.min_notional:
                    self.events.append({"ts": ts.isoformat(), "type": "insufficient_cash", "symbol": order.symbol})
                    continue
                result = result.__class__(affordable, result.price, affordable * result.price * self.cfg.backtest.fees.rate_bps / 1e4, result.slippage_cost * affordable / result.qty, result.cancelled_qty + result.qty - affordable, "cash_cap")
            trade = portfolio.apply_fill(
                ts_signal=ts_signal,
                ts_fill=ts.to_pydatetime(),
                symbol=order.symbol,
                side=order.side,
                qty=result.qty,
                price=result.price,
                fee=result.fee,
                slippage_cost=result.slippage_cost,
                reason=order.reason,
            )
            self.strategy.on_fill(Fill(trade.ts_fill, trade.symbol, trade.side, trade.qty, trade.price, trade.fee, trade.reason))


def _majority(regimes: dict[str, dict[str, float]], name: str) -> float:
    vals = [r[name] for r in regimes.values() if r[name] == r[name]]
    if not vals:
        return float("nan")
    return float(pd.Series(vals).mode().iloc[0])
