"""SQLite state store (WAL mode). Every cycle's write is one transaction keyed by ``(run_id, bar_ts)``.

Tables: ``runs, cycles, orders, fills, positions_snapshot, equity, events, halt, llm_usage``.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from kestrel.clock import ensure_utc

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY, strategy TEXT, market TEXT, config_json TEXT, started_at TEXT, last_seen_at TEXT
);
CREATE TABLE IF NOT EXISTS cycles (
  run_id TEXT, bar_ts TEXT, cycle_ts TEXT, status TEXT, summary_json TEXT, strategy_state_json TEXT,
  PRIMARY KEY (run_id, bar_ts)
);
CREATE TABLE IF NOT EXISTS orders (
  client_order_id TEXT PRIMARY KEY, run_id TEXT, bar_ts TEXT, order_id TEXT, symbol TEXT, side TEXT,
  qty REAL, status TEXT, submitted_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS fills (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, bar_ts TEXT, client_order_id TEXT, symbol TEXT,
  side TEXT, qty REAL, price REAL, fee REAL, ts TEXT, reason TEXT
);
CREATE TABLE IF NOT EXISTS positions_snapshot (
  run_id TEXT, bar_ts TEXT, symbol TEXT, qty REAL, avg_cost REAL, market_value REAL,
  PRIMARY KEY (run_id, bar_ts, symbol)
);
CREATE TABLE IF NOT EXISTS equity (
  run_id TEXT, bar_ts TEXT, equity REAL, cash REAL, PRIMARY KEY (run_id, bar_ts)
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, bar_ts TEXT, ts TEXT, type TEXT, payload_json TEXT
);
CREATE TABLE IF NOT EXISTS halt (
  config_key TEXT PRIMARY KEY, halted INTEGER, reason TEXT, since TEXT
);
CREATE TABLE IF NOT EXISTS signals (
  run_id TEXT, bar_ts TEXT, symbol TEXT, weight REAL, PRIMARY KEY (run_id, bar_ts, symbol)
);
CREATE TABLE IF NOT EXISTS llm_usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, provider TEXT, model TEXT, input_tokens INTEGER, output_tokens INTEGER, purpose TEXT
);
CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, ts TEXT, path TEXT
);
"""


class StateStore:
    """Thin, transactional wrapper over sqlite3."""

    def __init__(self, path: Path | str, *, config_key: str = "default") -> None:
        """Open (and create) the database at ``path``."""
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.config_key = config_key
        self._conn = sqlite3.connect(str(self.path), isolation_level=None, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        """Close the connection."""
        self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """``BEGIN IMMEDIATE`` ... ``COMMIT`` or ``ROLLBACK``."""
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield self._conn
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        else:
            self._conn.execute("COMMIT")

    # ------------------------------------------------------------------ runs

    def start_run(self, run_id: str, strategy: str, market: str, config: dict[str, Any], now: datetime) -> None:
        """Insert or touch a run row."""
        with self.transaction() as c:
            c.execute(
                "INSERT INTO runs(run_id, strategy, market, config_json, started_at, last_seen_at) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(run_id) DO UPDATE SET last_seen_at=excluded.last_seen_at",
                (run_id, strategy, market, json.dumps(config, sort_keys=True, default=str), ensure_utc(now).isoformat(), ensure_utc(now).isoformat()),
            )

    def last_cycle(self, run_id: str) -> dict[str, Any] | None:
        """Most recent persisted cycle for the run."""
        row = self._conn.execute("SELECT * FROM cycles WHERE run_id=? ORDER BY bar_ts DESC LIMIT 1", (run_id,)).fetchone()
        return dict(row) if row else None

    def last_bar_ts(self, run_id: str) -> datetime | None:
        """Timestamp of the last persisted bar."""
        row = self.last_cycle(run_id)
        return datetime.fromisoformat(row["bar_ts"]) if row else None

    # ------------------------------------------------------------------ cycle persistence

    def persist_cycle(
        self,
        *,
        run_id: str,
        bar_ts: datetime,
        cycle_ts: datetime,
        status: str,
        summary: dict[str, Any],
        strategy_state: dict[str, Any],
        positions: list[dict[str, Any]],
        equity: float,
        cash: float,
        signals: dict[str, float],
        orders: list[dict[str, Any]],
        fills: list[dict[str, Any]],
        events: list[dict[str, Any]],
    ) -> None:
        """Write everything from one cycle in a single transaction."""
        b = ensure_utc(bar_ts).isoformat()
        with self.transaction() as c:
            c.execute(
                "INSERT OR REPLACE INTO cycles VALUES(?,?,?,?,?,?)",
                (run_id, b, ensure_utc(cycle_ts).isoformat(), status, json.dumps(summary, default=str), json.dumps(strategy_state, default=str)),
            )
            c.execute("DELETE FROM positions_snapshot WHERE run_id=? AND bar_ts=?", (run_id, b))
            for p in positions:
                c.execute("INSERT INTO positions_snapshot VALUES(?,?,?,?,?,?)", (run_id, b, p["symbol"], float(p["qty"]), float(p["avg_cost"]), float(p["market_value"])))
            c.execute("INSERT OR REPLACE INTO equity VALUES(?,?,?,?)", (run_id, b, float(equity), float(cash)))
            c.execute("DELETE FROM signals WHERE run_id=? AND bar_ts=?", (run_id, b))
            for s, w in signals.items():
                c.execute("INSERT INTO signals VALUES(?,?,?,?)", (run_id, b, s, float(w)))
            for o in orders:
                c.execute(
                    "INSERT OR REPLACE INTO orders VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (o["client_order_id"], run_id, b, o.get("order_id"), o["symbol"], o["side"], float(o["qty"]), o["status"], o.get("submitted_at"), o.get("updated_at")),
                )
            for f in fills:
                c.execute(
                    "INSERT INTO fills(run_id, bar_ts, client_order_id, symbol, side, qty, price, fee, ts, reason) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (run_id, b, f.get("client_order_id"), f["symbol"], f["side"], float(f["qty"]), float(f["price"]), float(f.get("fee", 0)), f.get("ts"), f.get("reason", "signal")),
                )
            for e in events:
                c.execute("INSERT INTO events(run_id, bar_ts, ts, type, payload_json) VALUES(?,?,?,?,?)", (run_id, b, e.get("ts"), e["type"], json.dumps(e, default=str)))
            c.execute("UPDATE runs SET last_seen_at=? WHERE run_id=?", (ensure_utc(cycle_ts).isoformat(), run_id))

    def add_event(self, run_id: str, bar_ts: datetime | None, ts: datetime, type_: str, payload: dict[str, Any]) -> None:
        """Append one event outside a cycle."""
        with self.transaction() as c:
            c.execute(
                "INSERT INTO events(run_id, bar_ts, ts, type, payload_json) VALUES(?,?,?,?,?)",
                (run_id, ensure_utc(bar_ts).isoformat() if bar_ts else None, ensure_utc(ts).isoformat(), type_, json.dumps(payload, default=str)),
            )

    # ------------------------------------------------------------------ halt

    def set_halt(self, halted: bool, reason: str, since: datetime | None) -> None:
        """Write the halt flag."""
        with self.transaction() as c:
            c.execute(
                "INSERT OR REPLACE INTO halt VALUES(?,?,?,?)",
                (self.config_key, int(halted), reason, ensure_utc(since).isoformat() if since else None),
            )

    def get_halt(self) -> dict[str, Any]:
        """Read the halt flag."""
        row = self._conn.execute("SELECT * FROM halt WHERE config_key=?", (self.config_key,)).fetchone()
        if row is None:
            return {"halted": False, "reason": "", "since": None}
        return {"halted": bool(row["halted"]), "reason": row["reason"], "since": row["since"]}

    # ------------------------------------------------------------------ orders

    def open_orders(self, run_id: str | None = None) -> list[dict[str, Any]]:
        """Orders not in a terminal state (optionally for one run)."""
        q = "SELECT * FROM orders WHERE status IN ('new','open','partially_filled')"
        rows = self._conn.execute(q + (" AND run_id=?" if run_id else ""), (run_id,) if run_id else ()).fetchall()
        return [dict(r) for r in rows]

    def update_order(self, client_order_id: str, status: str, order_id: str | None, updated_at: datetime) -> None:
        """Update an order's status."""
        with self.transaction() as c:
            c.execute("UPDATE orders SET status=?, order_id=COALESCE(?, order_id), updated_at=? WHERE client_order_id=?", (status, order_id, ensure_utc(updated_at).isoformat(), client_order_id))

    # ------------------------------------------------------------------ reads for Telegram and CLI

    def _latest_run(self) -> str | None:
        row = self._conn.execute("SELECT run_id FROM runs ORDER BY last_seen_at DESC LIMIT 1").fetchone()
        return str(row["run_id"]) if row else None

    def status(self) -> dict[str, Any]:
        """Run id, strategy, last cycle, halt."""
        run_id = self._latest_run()
        out: dict[str, Any] = {"run_id": run_id, "halt": self.get_halt()}
        if run_id:
            r = self._conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            out.update({"strategy": r["strategy"], "market": r["market"], "started_at": r["started_at"]})
            c = self.last_cycle(run_id)
            if c:
                out.update({"last_cycle_ts": c["cycle_ts"], "last_bar_ts": c["bar_ts"], "last_status": c["status"]})
        return out

    def equity_summary(self) -> dict[str, Any]:
        """Equity, cash, day and week PnL, drawdown from peak."""
        run_id = self._latest_run()
        if not run_id:
            return {}
        rows = self._conn.execute("SELECT bar_ts, equity, cash FROM equity WHERE run_id=? ORDER BY bar_ts", (run_id,)).fetchall()
        if not rows:
            return {}
        last = rows[-1]
        last_ts = datetime.fromisoformat(last["bar_ts"])
        peak = max(r["equity"] for r in rows)

        def at(delta: timedelta) -> float:
            cutoff = (last_ts - delta).isoformat()
            prior = [r for r in rows if r["bar_ts"] <= cutoff]
            return float(prior[-1]["equity"]) if prior else float(rows[0]["equity"])

        return {
            "equity": float(last["equity"]),
            "cash": float(last["cash"]),
            "day_pnl": float(last["equity"]) - at(timedelta(days=1)),
            "week_pnl": float(last["equity"]) - at(timedelta(days=7)),
            "drawdown": float(last["equity"]) / peak - 1.0 if peak > 0 else 0.0,
            "peak": float(peak),
            "as_of": last["bar_ts"],
        }

    def positions(self) -> list[dict[str, Any]]:
        """Latest snapshot."""
        run_id = self._latest_run()
        if not run_id:
            return []
        c = self.last_cycle(run_id)
        if not c:
            return []
        rows = self._conn.execute("SELECT symbol, qty, avg_cost, market_value FROM positions_snapshot WHERE run_id=? AND bar_ts=? ORDER BY symbol", (run_id, c["bar_ts"])).fetchall()
        return [dict(r) for r in rows]

    def recent_trades(self, n: int = 10) -> list[dict[str, Any]]:
        """Last ``n`` fills."""
        rows = self._conn.execute("SELECT symbol, side, qty, price, fee, ts, reason FROM fills ORDER BY id DESC LIMIT ?", (n,)).fetchall()
        return [dict(r) for r in rows]

    def trades_since(self, since: datetime) -> list[dict[str, Any]]:
        """Fills with ``ts >= since``."""
        rows = self._conn.execute("SELECT symbol, side, qty, price, fee, ts, reason FROM fills WHERE ts >= ? ORDER BY id", (ensure_utc(since).isoformat(),)).fetchall()
        return [dict(r) for r in rows]

    def last_signals(self) -> dict[str, float]:
        """Target weights from the last cycle."""
        run_id = self._latest_run()
        if not run_id:
            return {}
        c = self.last_cycle(run_id)
        if not c:
            return {}
        rows = self._conn.execute("SELECT symbol, weight FROM signals WHERE run_id=? AND bar_ts=?", (run_id, c["bar_ts"])).fetchall()
        return {r["symbol"]: float(r["weight"]) for r in rows}

    def recent_events(self, n: int = 20, types: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
        """Last ``n`` events, optionally filtered by type."""
        if types:
            marks = ",".join("?" * len(types))
            rows = self._conn.execute(f"SELECT * FROM events WHERE type IN ({marks}) ORDER BY id DESC LIMIT ?", (*types, n)).fetchall()  # noqa: S608
        else:
            rows = self._conn.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (n,)).fetchall()
        return [dict(r) for r in rows]

    def record_report(self, run_id: str, ts: datetime, path: Path) -> None:
        """Remember a generated report path."""
        with self.transaction() as c:
            c.execute("INSERT INTO reports(run_id, ts, path) VALUES(?,?,?)", (run_id, ensure_utc(ts).isoformat(), str(path)))

    def latest_report(self) -> Path | None:
        """Most recent report path."""
        row = self._conn.execute("SELECT path FROM reports ORDER BY id DESC LIMIT 1").fetchone()
        return Path(row["path"]) if row else None

    def equity_frame(self, run_id: str | None = None) -> list[tuple[str, float, float]]:
        """``(bar_ts, equity, cash)`` rows for the run."""
        rid = run_id or self._latest_run()
        if not rid:
            return []
        rows = self._conn.execute("SELECT bar_ts, equity, cash FROM equity WHERE run_id=? ORDER BY bar_ts", (rid,)).fetchall()
        return [(r["bar_ts"], float(r["equity"]), float(r["cash"])) for r in rows]

    # ------------------------------------------------------------------ llm usage

    def add_llm_usage(self, ts: datetime, provider: str, model: str, input_tokens: int, output_tokens: int, purpose: str) -> None:
        """Record one model call."""
        with self.transaction() as c:
            c.execute("INSERT INTO llm_usage(ts, provider, model, input_tokens, output_tokens, purpose) VALUES(?,?,?,?,?,?)", (ensure_utc(ts).isoformat(), provider, model, input_tokens, output_tokens, purpose))

    def llm_tokens_since(self, since: datetime) -> int:
        """Total tokens used since ``since``."""
        row = self._conn.execute("SELECT COALESCE(SUM(input_tokens + output_tokens), 0) AS n FROM llm_usage WHERE ts >= ?", (ensure_utc(since).isoformat(),)).fetchone()
        return int(row["n"])
