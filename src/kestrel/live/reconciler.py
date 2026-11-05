"""Reconcile local state with the broker. The broker is always right."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from kestrel.execution.protocol import Balance, Position


@dataclass
class ReconcileResult:
    """What the broker says versus what we thought."""

    positions: dict[str, float]
    avg_costs: dict[str, float]
    cash: float
    equity: float
    drift_notional: float
    diffs: list[dict[str, Any]] = field(default_factory=list)

    @property
    def drift_fraction(self) -> float:
        """Drift as a fraction of equity."""
        return self.drift_notional / self.equity if self.equity > 0 else 0.0


class Reconciler:
    """Compare broker positions and balance to the last local snapshot."""

    @staticmethod
    def reconcile(
        broker_positions: list[Position],
        broker_balance: Balance,
        local_positions: dict[str, float],
        local_cash: float | None,
        prices: dict[str, float],
    ) -> ReconcileResult:
        """Return the broker's view plus the diff against local state."""
        bp = {p.symbol: float(p.qty) for p in broker_positions if p.qty > 0}
        costs = {p.symbol: float(p.avg_cost) for p in broker_positions if p.qty > 0}
        diffs: list[dict[str, Any]] = []
        drift = 0.0
        for sym in sorted(set(bp) | set(local_positions)):
            b, local = bp.get(sym, 0.0), local_positions.get(sym, 0.0)
            if abs(b - local) > 1e-9:
                notional = abs(b - local) * prices.get(sym, 0.0)
                drift += notional
                diffs.append({"symbol": sym, "broker_qty": b, "local_qty": local, "notional": notional})
        cash = float(broker_balance.cash)
        if local_cash is not None and abs(cash - local_cash) > max(1.0, 1e-6 * abs(cash)):
            diffs.append({"symbol": "CASH", "broker_qty": cash, "local_qty": local_cash, "notional": abs(cash - local_cash)})
            drift += abs(cash - local_cash)
        return ReconcileResult(bp, costs, cash, float(broker_balance.equity), drift, diffs)

    @staticmethod
    def positions_from(result: ReconcileResult, prices: dict[str, float]) -> list[dict[str, Any]]:
        """Snapshot rows for the state store."""
        return [
            {"symbol": s, "qty": q, "avg_cost": result.avg_costs.get(s, 0.0), "market_value": q * prices.get(s, 0.0)}
            for s, q in sorted(result.positions.items())
        ]


def to_decimal(x: float) -> Decimal:
    """Convert once at the adapter boundary."""
    return Decimal(str(x))
