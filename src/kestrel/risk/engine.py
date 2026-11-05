"""RiskEngine: stateful halt logic plus the targets-to-orders pipeline.

The engine has veto power. It is the only component allowed to flatten the book, which it does
by returning ``risk_exit`` orders; the caller (backtester or live runner) executes them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from kestrel.clock import ensure_utc
from kestrel.config import RiskConfig
from kestrel.risk.limits import LimitReport, clamp_weights, weights_to_orders
from kestrel.risk.sizing import size_fixed_fraction, size_vol_target
from kestrel.types import MarketMeta, OrderIntent


@dataclass(frozen=True)
class HaltState:
    """Whether trading is halted and why."""

    halted: bool
    reason: str = ""
    since: datetime | None = None
    until_next_day: bool = False

    @property
    def active(self) -> bool:
        """Alias for ``halted``."""
        return self.halted


class RiskEngine:
    """Sizing, limits and halts for one run."""

    def __init__(self, cfg: RiskConfig, *, initial_equity: float) -> None:
        """Create an engine tracking peak and start-of-day equity from ``initial_equity``."""
        self.cfg = cfg
        self.peak_equity = float(initial_equity)
        self.sod_equity = float(initial_equity)
        self._sod_date: object = None
        self._halt = HaltState(False)
        self.consecutive_adapter_errors = 0
        self.stale_skips = 0
        self.breaches: list[tuple[datetime, str]] = []
        self.clamped_shorts = 0

    # ------------------------------------------------------------------ halt state

    @property
    def halt(self) -> HaltState:
        """Current halt state."""
        return self._halt

    def set_halt(self, reason: str, ts: datetime, *, until_next_day: bool = False) -> bool:
        """Halt. Returns True if this call changed the state (so flattening happens once)."""
        if self._halt.halted:
            return False
        self._halt = HaltState(True, reason, ensure_utc(ts), until_next_day)
        self.breaches.append((ensure_utc(ts), reason))
        return True

    def clear_halt(self) -> None:
        """Resume trading."""
        self._halt = HaltState(False)

    def flatten_orders(self, positions: Mapping[str, float], prices: Mapping[str, float]) -> list[OrderIntent]:
        """Market sells for every open position (idempotent: nothing to sell returns nothing)."""
        out: list[OrderIntent] = []
        for s, q in sorted(positions.items()):
            if q > 0 and prices.get(s, 0.0) > 0:
                out.append(OrderIntent(s, "sell", q, prices[s], "risk_exit"))
        return out

    # ------------------------------------------------------------------ monitoring

    def on_equity(self, ts: datetime, equity: float) -> str | None:
        """Update peak and start-of-day equity; return a breach reason if a limit is hit.

        Daily-loss halts lift automatically on the next UTC day; drawdown halts need a resume.
        """
        t = ensure_utc(ts)
        day = t.date()
        if self._sod_date != day:
            self._sod_date = day
            self.sod_equity = equity if self._sod_date is None else self.sod_equity_for_new_day(equity)
            if self._halt.halted and self._halt.until_next_day:
                self.clear_halt()
        self.peak_equity = max(self.peak_equity, equity)
        if self.sod_equity > 0 and equity / self.sod_equity - 1.0 <= -self.cfg.max_daily_loss:
            if self.set_halt(f"daily loss {equity / self.sod_equity - 1.0:.2%} exceeds {self.cfg.max_daily_loss:.0%}", t, until_next_day=True):
                return self._halt.reason
        if self.peak_equity > 0 and equity / self.peak_equity - 1.0 <= -self.cfg.max_drawdown:
            if self.set_halt(f"drawdown {equity / self.peak_equity - 1.0:.2%} exceeds {self.cfg.max_drawdown:.0%}", t):
                return self._halt.reason
        return None

    def sod_equity_for_new_day(self, equity_at_first_mark: float) -> float:
        """Start-of-day equity is the last known equity when the day rolls over."""
        return self._last_equity if hasattr(self, "_last_equity") else equity_at_first_mark

    def record_equity(self, equity: float) -> None:
        """Remember the latest equity so the next day's start-of-day reference is exact."""
        self._last_equity = equity

    def on_adapter_error(self, ts: datetime) -> str | None:
        """Count a consecutive adapter error; halt when the limit is hit."""
        self.consecutive_adapter_errors += 1
        if self.consecutive_adapter_errors >= self.cfg.max_consecutive_adapter_errors:
            if self.set_halt(f"{self.consecutive_adapter_errors} consecutive adapter errors", ts):
                return self._halt.reason
        return None

    def on_adapter_ok(self) -> None:
        """Reset the adapter error streak."""
        self.consecutive_adapter_errors = 0

    def is_stale(self, last_bar_ts: datetime, now: datetime, bar_seconds: int) -> bool:
        """Whether the newest bar is older than ``stale_data_bars`` bar lengths."""
        age = (ensure_utc(now) - ensure_utc(last_bar_ts)).total_seconds()
        return age > self.cfg.stale_data_bars * bar_seconds + bar_seconds

    # ------------------------------------------------------------------ orders

    def targets_to_orders(
        self,
        targets: Mapping[str, float],
        *,
        equity: float,
        positions: Mapping[str, float],
        prices: Mapping[str, float],
        meta: Mapping[str, MarketMeta],
        vols: Mapping[str, float] | None = None,
        reason: str = "signal",
    ) -> tuple[list[OrderIntent], LimitReport]:
        """Size, clamp and convert targets into orders; empty while halted."""
        report = LimitReport()
        if self._halt.halted:
            report.notes.append(f"halted: {self._halt.reason}")
            return [], report
        negatives = {s: w for s, w in targets.items() if w < 0}
        report.clamped_shorts += len(negatives)
        self.clamped_shorts += len(negatives)
        positive = {s: w for s, w in targets.items() if w > 0}
        if self.cfg.sizing == "vol_target":
            sized = size_vol_target(
                positive,
                vols or {},
                target_vol=self.cfg.target_vol,
                max_weight=self.cfg.max_weight_per_symbol,
                max_gross=self.cfg.max_gross_exposure,
            )
        else:
            sized = size_fixed_fraction(positive, self.cfg.max_gross_exposure)
        weights = clamp_weights(sized, self.cfg, report)
        orders = weights_to_orders(
            weights,
            equity=equity,
            positions=positions,
            prices=prices,
            meta=meta,
            cfg=self.cfg,
            report=report,
            reason=reason,
        )
        return orders, report
