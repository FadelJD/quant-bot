"""The kill switch: cancel, flatten, persist HALTED, notify. Idempotent."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from kestrel.clock import Clock
from kestrel.errors import AdapterError
from kestrel.execution.protocol import MarketAdapter, OrderRequest
from kestrel.execution.safety import client_order_id
from kestrel.live.state import StateStore
from kestrel.logsetup import get_logger
from kestrel.notify.base import Alert, Notifier

log = get_logger(__name__)


class KillSwitch:
    """``halt(reason)`` cancels open orders, flattens every position, writes the flag, notifies."""

    def __init__(self, adapter: MarketAdapter, store: StateStore, notifier: Notifier, clock: Clock, *, strategy: str) -> None:
        """Bind to one adapter, store and notifier."""
        self.adapter = adapter
        self.store = store
        self.notifier = notifier
        self.clock = clock
        self.strategy = strategy
        self.flatten_count = 0

    def halt(self, reason: str, bar_ts: datetime | None = None) -> bool:
        """Halt. Returns False (and does nothing) if already halted."""
        current = self.store.get_halt()
        if current["halted"]:
            log.info("halt_already_active", reason=current["reason"])
            return False
        now = self.clock.now()
        self.store.set_halt(True, reason, now)
        log.critical("halt", reason=reason)
        try:
            for o in self.adapter.get_open_orders():
                self.adapter.cancel_order(o.order_id)
            stamp = bar_ts or now
            for n, p in enumerate(self.adapter.get_positions()):
                if p.qty > 0:
                    req = OrderRequest(p.symbol, "sell", Decimal(str(p.qty)), client_order_id(self.strategy, p.symbol, stamp, 9000 + n))
                    self.adapter.place_order(req)
                    self.flatten_count += 1
        except AdapterError as exc:
            log.error("halt_flatten_failed", error=str(exc))
            self.store.add_event("halt", bar_ts, now, "halt_flatten_failed", {"error": str(exc)})
        self.notifier.send(Alert("halt", "kestrel halted", f"reason: {reason}\nall positions flattened, open orders cancelled"))
        return True

    def resume(self, confirmation: str) -> bool:
        """Clear the halt only if ``confirmation`` matches the halt reason."""
        current = self.store.get_halt()
        if not current["halted"]:
            return True
        if confirmation.strip().lower() != str(current["reason"]).strip().lower():
            return False
        self.store.set_halt(False, "", None)
        log.warning("resumed", previous_reason=current["reason"])
        return True
