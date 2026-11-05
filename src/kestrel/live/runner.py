"""LiveRunner: one cycle per bar close, reconcile first, never act on unreconciled state."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from kestrel.clock import Clock, ensure_utc
from kestrel.config import RunConfig
from kestrel.data.calendar import MarketCalendar, calendar_for
from kestrel.errors import AdapterError, DataError, KestrelError
from kestrel.execution.protocol import MarketAdapter, Order, OrderRequest
from kestrel.execution.safety import client_order_id
from kestrel.features.builder import FeatureBuilder
from kestrel.live.kill_switch import KillSwitch
from kestrel.live.reconciler import Reconciler
from kestrel.live.state import StateStore
from kestrel.logsetup import get_logger
from kestrel.notify.base import Alert, Notifier
from kestrel.risk.engine import RiskEngine
from kestrel.strategies.base import BarContext, Fill, PositionView, Strategy, validate_targets
from kestrel.types import MarketMeta

log = get_logger(__name__)

REGIME_FEATURES = ("vol_regime_20_250", "trend_regime_200")


class LiveRunner:
    """Drive a strategy against an adapter, bar by bar, through the risk layer and the state store."""

    def __init__(
        self,
        cfg: RunConfig,
        *,
        strategy: Strategy,
        adapter: MarketAdapter,
        clock: Clock,
        store: StateStore,
        notifier: Notifier,
        symbols: tuple[str, ...],
        run_id: str,
        calendar: MarketCalendar | None = None,
        history_bars: int = 400,
        reports_dir: Path | None = None,
    ) -> None:
        """Wire the runner. Nothing touches the network until :meth:`start`."""
        self.cfg = cfg
        self.strategy = strategy
        self.adapter = adapter
        self.clock = clock
        self.store = store
        self.notifier = notifier
        self.symbols = tuple(sorted(symbols))
        self.run_id = run_id
        self.calendar = calendar or calendar_for(cfg.market)
        self.history_bars = history_bars
        self.reports_dir = reports_dir or cfg.reports_dir
        self.risk = RiskEngine(cfg.risk, initial_equity=1.0)
        self.kill = KillSwitch(adapter, store, notifier, clock, strategy=strategy.name)
        self.features = FeatureBuilder(per_year=cfg.annualisation)
        self.meta: dict[str, MarketMeta] = {}
        self.local_positions: dict[str, float] = {}
        self.local_cash: float | None = None
        self.bar_seconds = cfg.bar_seconds
        self.cycles_run = 0
        self.missed_bars = 0
        self.last_daily_report: datetime | None = None
        self._order_seq = 0
        self._initialised = False
        self._stale_streak = 0

    # ------------------------------------------------------------------ lifecycle

    def start(self) -> None:
        """Register the run, load metadata, recover state, and handle orphaned orders."""
        now = self.clock.now()
        self.store.start_run(self.run_id, self.strategy.name, self.cfg.market, self.cfg.model_dump(mode="json"), now)
        for s in self.symbols:
            try:
                self.meta[s] = self.adapter.market_meta(s)
            except KestrelError as exc:
                log.warning("market_meta_unavailable", symbol=s, error=str(exc))
        last = self.store.last_cycle(self.run_id)
        if last:
            try:
                self.strategy.load_state(json.loads(last["strategy_state_json"] or "{}"))
            except (ValueError, TypeError):
                log.warning("strategy_state_unreadable")
            last_bar = datetime.fromisoformat(last["bar_ts"])
            missed = int((now - last_bar).total_seconds() // self.bar_seconds) - 1
            if missed > 0:
                self.missed_bars = missed
                log.warning("missed_bars", n=missed, last_bar=last_bar.isoformat())
                self.store.add_event(self.run_id, None, now, "missed_bars", {"n": missed, "last_bar": last_bar.isoformat()})
            self.local_positions = {p["symbol"]: float(p["qty"]) for p in self.store.positions()}
            eq = self.store.equity_summary()
            self.local_cash = float(eq["cash"]) if eq else None
            if eq:
                self.risk.peak_equity = float(eq.get("peak", eq["equity"]))
        self._recover_orphans(now)
        balance = self.adapter.get_balance()
        self.risk.peak_equity = max(self.risk.peak_equity, float(balance.equity))
        self.risk.sod_equity = float(balance.equity)
        self.risk.record_equity(float(balance.equity))
        self._initialised = True
        log.info("runner_started", run_id=self.run_id, symbols=list(self.symbols))

    def _recover_orphans(self, now: datetime) -> None:
        """Open orders from a previous run: record filled ones, cancel stale ones."""
        local_open = self.store.open_orders(self.run_id)
        if not local_open:
            return
        try:
            broker_open = {o.client_order_id: o for o in self.adapter.get_open_orders()}
        except AdapterError as exc:
            log.error("orphan_lookup_failed", error=str(exc))
            return
        for row in local_open:
            cid = row["client_order_id"]
            broker = broker_open.get(cid)
            if broker is None:
                status = "filled"
                if row.get("order_id"):
                    try:
                        status = self.adapter.get_order(row["order_id"]).status
                    except AdapterError:
                        status = "unknown"
                self.store.update_order(cid, status, row.get("order_id"), now)
                self.store.add_event(self.run_id, None, now, "orphan_order_resolved", {"client_order_id": cid, "status": status})
            else:
                self.adapter.cancel_order(broker.order_id)
                self.store.update_order(cid, "cancelled", broker.order_id, now)
                self.store.add_event(self.run_id, None, now, "orphan_order_cancelled", {"client_order_id": cid})

    # ------------------------------------------------------------------ scheduling

    def next_cycle_time(self, after: datetime) -> datetime:
        """Next bar close plus the configured offset."""
        return self.calendar.next_bar_close(after, self.cfg.timeframe) + timedelta(seconds=self.cfg.live.cycle_offset_s)

    def run_until(self, end: datetime, *, max_cycles: int | None = None) -> int:
        """Run cycles until the clock passes ``end``. Returns the number of cycles run."""
        if not self._initialised:
            self.start()
        n = 0
        end = ensure_utc(end)
        while True:
            now = self.clock.now()
            nxt = self.next_cycle_time(now)
            if nxt > end or (max_cycles is not None and n >= max_cycles):
                return n
            self.clock.sleep_until(nxt)
            self.run_cycle()
            n += 1

    def run_forever(self) -> None:  # pragma: no cover - the owner runs this
        """Run until interrupted."""
        if not self._initialised:
            self.start()
        while True:
            nxt = self.next_cycle_time(self.clock.now())
            self.clock.sleep_until(nxt)
            self.run_cycle()

    # ------------------------------------------------------------------ one cycle

    def run_cycle(self) -> dict[str, Any]:
        """Execute one cycle and persist it. Never raises on adapter errors; halts on streaks."""
        now = self.clock.now()
        bar_ts = self._bar_ts_for(now)
        summary: dict[str, Any] = {"bar_ts": bar_ts.isoformat(), "status": "ok"}
        events: list[dict[str, Any]] = []
        try:
            summary = self._cycle(now, bar_ts, events)
            self.risk.on_adapter_ok()
        except AdapterError as exc:
            log.error("adapter_error", error=str(exc))
            events.append({"ts": now.isoformat(), "type": "adapter_error", "error": str(exc)})
            summary["status"] = "adapter_error"
            reason = self.risk.on_adapter_error(now)
            if reason:
                self.kill.halt(reason, bar_ts)
                self.notifier.send(Alert("adapter_error_streak", "adapter error streak", reason))
            self._persist(bar_ts, now, summary, [], [], events, {}, None)
        except DataError as exc:
            log.warning("data_error", error=str(exc))
            events.append({"ts": now.isoformat(), "type": "data_error", "error": str(exc)})
            summary["status"] = "data_error"
            self._persist(bar_ts, now, summary, [], [], events, {}, None)
        except Exception as exc:
            log.exception("cycle_crashed")
            self.notifier.send(Alert("halt", "kestrel cycle crashed", f"{type(exc).__name__}: {exc}", severity="critical"))
            raise
        self.cycles_run += 1
        self._maybe_daily_report(now)
        return summary

    def _bar_ts_for(self, now: datetime) -> datetime:
        """Open time of the bar that just closed."""
        if self.cfg.timeframe == "1d" and self.cfg.market == "equities":
            sess = self.calendar.sessions(now - timedelta(days=7), now)
            opens = [t.to_pydatetime() for t in sess if t.to_pydatetime() <= now]
            return opens[-1] if opens else now
        epoch = int(now.timestamp())
        closed = (epoch // self.bar_seconds) * self.bar_seconds - self.bar_seconds
        return datetime.fromtimestamp(closed, tz=ensure_utc(now).tzinfo)

    def _cycle(self, now: datetime, bar_ts: datetime, events: list[dict[str, Any]]) -> dict[str, Any]:
        summary: dict[str, Any] = {"bar_ts": bar_ts.isoformat(), "status": "ok"}

        # 1. Reconcile.
        prices = self._last_prices()
        rec = Reconciler.reconcile(self.adapter.get_positions(), self.adapter.get_balance(), self.local_positions, self.local_cash, prices)
        if rec.diffs:
            events.append({"ts": now.isoformat(), "type": "reconcile_drift", "diffs": rec.diffs, "drift_fraction": rec.drift_fraction})
            log.warning("reconcile_drift", diffs=rec.diffs)
            if rec.drift_fraction > self.cfg.live.drift_notify_fraction:
                self.notifier.send(Alert("reconcile_drift", "reconcile drift", f"{rec.drift_fraction:.2%} of equity\n" + "\n".join(f"{d['symbol']}: broker {d['broker_qty']} local {d['local_qty']}" for d in rec.diffs)))
        self.local_positions = dict(rec.positions)
        self.local_cash = rec.cash
        equity = rec.equity
        summary.update({"equity": equity, "cash": rec.cash, "drift": rec.drift_fraction})

        # 2. Halt flag.
        halt = self.store.get_halt()
        if halt["halted"]:
            summary["status"] = "halted"
            self._persist(bar_ts, now, summary, Reconciler.positions_from(rec, prices), [], events, {}, None)
            return summary

        # 3. Bars.
        start = bar_ts - timedelta(seconds=self.bar_seconds * self.history_bars)
        frames = {s: self.adapter.get_bars(s, self.cfg.timeframe, start, bar_ts) for s in self.symbols}
        frames = {s: f for s, f in frames.items() if not f.empty}
        if not frames:
            raise DataError("no bars returned for any symbol")
        newest = max(f.index[-1].to_pydatetime() for f in frames.values())
        if self.risk.is_stale(newest, now, self.bar_seconds):
            self._stale_streak += 1
            events.append({"ts": now.isoformat(), "type": "stale_data", "newest": newest.isoformat(), "streak": self._stale_streak})
            summary["status"] = "stale_skipped"
            if self._stale_streak >= self.cfg.risk.stale_notify_after:
                self.notifier.send(Alert("stale_data", "stale data", f"newest bar {newest.isoformat()}, {self._stale_streak} cycles skipped"))
            self._persist(bar_ts, now, summary, Reconciler.positions_from(rec, prices), [], events, {}, None)
            return summary
        self._stale_streak = 0
        closes = {s: float(f["close"].iloc[-1]) for s, f in frames.items()}
        prices.update(closes)

        # Risk monitoring on the reconciled equity.
        breach = self.risk.on_equity(now, equity)
        self.risk.record_equity(equity)
        if breach:
            self.kill.halt(breach, bar_ts)
            summary["status"] = "halted"
            self._persist(bar_ts, now, summary, Reconciler.positions_from(rec, prices), [], events, {}, None)
            return summary

        # 4. Features, strategy, risk.
        feats = self.features.build(frames, [*self.strategy.requires, *REGIME_FEATURES], timeframe=self.cfg.timeframe, cross_sectional=list(self.strategy.cross_sectional) or None)
        views = {s: PositionView(s, q, rec.avg_costs.get(s, 0.0), q * closes.get(s, 0.0)) for s, q in rec.positions.items() if q > 0}
        regimes = {s: {n: float(f.iloc[-1].get(n, float("nan"))) for n in REGIME_FEATURES} for s, f in feats.items()}
        ctx = BarContext(ts=feats[next(iter(feats))].index[-1].to_pydatetime(), features=feats, positions=views, cash=rec.cash, equity=equity, regimes=regimes, bar_index=self.cycles_run)
        targets = validate_targets(self.strategy.on_bar(ctx), self.symbols)
        vols = {s: float(f.iloc[-1].get("vol_20", float("nan"))) for s, f in feats.items()}
        orders, report = self.risk.targets_to_orders(targets, equity=equity, positions=rec.positions, prices=closes, meta=self.meta, vols=vols)
        summary.update({"n_targets": len(targets), "n_orders": len(orders), "limits": report.__dict__})

        # 5. Submit and poll.
        order_rows, fill_rows = self._execute(orders, bar_ts, now, events)
        summary["n_fills"] = len(fill_rows)

        # 6. Persist (positions re-read from the broker after fills).
        post_positions = self.adapter.get_positions()
        post_balance = self.adapter.get_balance()
        self.local_positions = {p.symbol: float(p.qty) for p in post_positions if p.qty > 0}
        self.local_cash = float(post_balance.cash)
        snapshot = [{"symbol": p.symbol, "qty": float(p.qty), "avg_cost": float(p.avg_cost), "market_value": float(p.market_value)} for p in post_positions if p.qty > 0]
        summary.update({"equity": float(post_balance.equity), "cash": float(post_balance.cash)})
        self._persist(bar_ts, now, summary, snapshot, order_rows, events, targets, fill_rows)

        # 7. Summary.
        log.info("cycle", **{k: v for k, v in summary.items() if k != "limits"})
        if fill_rows:
            body = "\n".join(f"{f['side']} {f['qty']:.4f} {f['symbol']} @ {f['price']:.2f}" for f in fill_rows)
            self.notifier.send(Alert("info", f"cycle {bar_ts:%Y-%m-%d %H:%M}: {len(fill_rows)} fill(s)", body))
        return summary

    def _last_prices(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for s in self.symbols:
            try:
                q = self.adapter.get_quote(s)
                out[s] = float((q.bid + q.ask) / 2)
            except AdapterError:
                continue
        return out

    def _execute(self, orders: list[Any], bar_ts: datetime, now: datetime, events: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        order_rows: list[dict[str, Any]] = []
        fill_rows: list[dict[str, Any]] = []
        for n, intent in enumerate(orders):
            self._order_seq += 1
            cid = client_order_id(self.strategy.name, intent.symbol, bar_ts, n)
            req = OrderRequest(intent.symbol, intent.side, Decimal(str(intent.qty)), cid)
            try:
                order = self.adapter.place_order(req)
            except AdapterError as exc:
                events.append({"ts": now.isoformat(), "type": "order_failed", "client_order_id": cid, "error": str(exc)})
                order_rows.append({"client_order_id": cid, "order_id": None, "symbol": intent.symbol, "side": intent.side, "qty": intent.qty, "status": "rejected", "submitted_at": now.isoformat(), "updated_at": now.isoformat()})
                continue
            order = self._poll(order, now)
            order_rows.append({"client_order_id": cid, "order_id": order.order_id, "symbol": order.symbol, "side": order.side, "qty": float(order.qty), "status": order.status, "submitted_at": order.submitted_at.isoformat(), "updated_at": order.updated_at.isoformat()})
            if order.filled_qty > 0 and order.avg_fill_price is not None:
                fill = {"client_order_id": cid, "symbol": order.symbol, "side": order.side, "qty": float(order.filled_qty), "price": float(order.avg_fill_price), "fee": float(order.fee), "ts": order.updated_at.isoformat(), "reason": intent.reason}
                fill_rows.append(fill)
                self.strategy.on_fill(Fill(order.updated_at, order.symbol, order.side, float(order.filled_qty), float(order.avg_fill_price), float(order.fee), intent.reason))
            if order.status == "rejected":
                events.append({"ts": now.isoformat(), "type": "order_rejected", "client_order_id": cid})
        return order_rows, fill_rows

    def _poll(self, order: Order, started: datetime) -> Order:
        """Poll until terminal or timeout; on timeout cancel and log."""
        deadline = started + timedelta(seconds=self.cfg.live.order_timeout_s)
        current = order
        while not current.terminal and current.status != "partially_filled":
            if self.clock.now() >= deadline:
                try:
                    self.adapter.cancel_order(current.order_id)
                    current = self.adapter.get_order(current.order_id)
                except AdapterError as exc:
                    log.error("cancel_failed", order_id=current.order_id, error=str(exc))
                log.warning("order_timeout_cancelled", client_order_id=current.client_order_id)
                break
            self.clock.sleep_until(self.clock.now() + timedelta(seconds=self.cfg.live.poll_interval_s))
            current = self.adapter.get_order(current.order_id)
        return current

    def _persist(self, bar_ts: datetime, now: datetime, summary: dict[str, Any], positions: list[dict[str, Any]], orders: list[dict[str, Any]], events: list[dict[str, Any]], signals: dict[str, float], fills: list[dict[str, Any]] | None) -> None:
        self.store.persist_cycle(
            run_id=self.run_id,
            bar_ts=bar_ts,
            cycle_ts=now,
            status=str(summary.get("status", "ok")),
            summary=summary,
            strategy_state=self.strategy.state(),
            positions=positions,
            equity=float(summary.get("equity", 0.0)),
            cash=float(summary.get("cash", 0.0)),
            signals=signals,
            orders=orders,
            fills=fills or [],
            events=events,
        )

    # ------------------------------------------------------------------ reports

    def _maybe_daily_report(self, now: datetime) -> None:
        tz = ZoneInfo(self.cfg.display_tz)
        local = now.astimezone(tz)
        hh, mm = (int(x) for x in self.cfg.live.daily_report_time.split(":"))
        due = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if local < due:
            return
        if self.last_daily_report is not None and self.last_daily_report.astimezone(tz).date() == local.date():
            return
        self.last_daily_report = now
        self.notifier.send(Alert("daily_report", f"kestrel daily report {local:%Y-%m-%d}", self.daily_report_text(now)))

    def daily_report_text(self, now: datetime) -> str:
        """Equity, day and week PnL, drawdown, positions, trades in the last 24 h, warnings."""
        eq = self.store.equity_summary()
        pos = self.store.positions()
        trades = self.store.trades_since(now - timedelta(hours=24))
        warnings = self.store.recent_events(5, ("reconcile_drift", "stale_data", "adapter_error", "order_rejected"))
        lines = [
            f"equity {eq.get('equity', 0):,.2f}  day {eq.get('day_pnl', 0):+,.2f}  week {eq.get('week_pnl', 0):+,.2f}",
            f"drawdown from peak {eq.get('drawdown', 0):.2%}",
            f"positions: {len(pos)}",
            *[f"  {p['symbol']} {float(p['qty']):.4f} ({float(p['market_value']):,.2f})" for p in pos[:10]],
            f"trades last 24h: {len(trades)}",
            *[f"  {t['side']} {float(t['qty']):.4f} {t['symbol']} @ {float(t['price']):.2f}" for t in trades[:10]],
        ]
        if warnings:
            lines.append("warnings:")
            lines.extend(f"  {w['type']} at {w['ts']}" for w in warnings)
        return "\n".join(lines)

    def equity_curve(self) -> pd.DataFrame:
        """Equity history from the store."""
        rows = self.store.equity_frame(self.run_id)
        if not rows:
            return pd.DataFrame(columns=["equity", "cash"]).rename_axis("ts")
        df = pd.DataFrame(rows, columns=["ts", "equity", "cash"])
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        return df.set_index("ts")
