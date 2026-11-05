"""Telegram notifier and bot command handlers with an injected transport.

The transport is the only thing that talks to Telegram. Tests use a fake that records messages.
``run_bot`` wires ``python-telegram-bot`` long polling; the agent never runs it.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from kestrel.config import NotifyConfig, Secrets
from kestrel.logsetup import get_logger
from kestrel.notify.base import Alert, ConsoleNotifier, Notifier, NullNotifier, RateLimitedNotifier

log = get_logger(__name__)

MAX_LINES = 40


class TelegramTransport(Protocol):
    """Minimal sending interface."""

    def send_message(self, chat_id: str, text: str) -> None:
        """Send plain text."""
        ...

    def send_document(self, chat_id: str, path: Path, caption: str = "") -> None:
        """Send a file."""
        ...


class RecordingTransport:
    """Fake transport for tests: records every message and document."""

    def __init__(self) -> None:
        """Start empty."""
        self.messages: list[tuple[str, str]] = []
        self.documents: list[tuple[str, Path, str]] = []

    def send_message(self, chat_id: str, text: str) -> None:
        """Record."""
        self.messages.append((chat_id, text))

    def send_document(self, chat_id: str, path: Path, caption: str = "") -> None:
        """Record."""
        self.documents.append((chat_id, path, caption))


def format_alert(alert: Alert) -> str:
    """Plain text, under 40 lines, with a fixed-width block for tables."""
    prefix = {"critical": "!!! ", "warning": "! ", "info": ""}[alert.level]
    lines = [f"{prefix}{alert.title}", *alert.body.splitlines()]
    if len(lines) > MAX_LINES:
        lines = [*lines[: MAX_LINES - 1], "..."]
    return "\n".join(lines)


class TelegramNotifier:
    """Sends alerts to one chat id."""

    name = "telegram"

    def __init__(self, transport: TelegramTransport, chat_id: str) -> None:
        """Create a notifier bound to ``chat_id``."""
        self.transport = transport
        self.chat_id = chat_id

    def send(self, alert: Alert) -> bool:
        """Send the text and the attachment if any."""
        try:
            self.transport.send_message(self.chat_id, format_alert(alert))
            if alert.attachment is not None and alert.attachment.exists():
                self.transport.send_document(self.chat_id, alert.attachment, alert.title)
        except Exception as exc:  # noqa: BLE001 - a notifier must never crash the loop
            log.error("telegram_send_failed", error=str(exc))
            return False
        return True


def build_notifier(cfg: NotifyConfig, secrets: Secrets, *, transport: TelegramTransport | None = None, clock: Any | None = None) -> Notifier:
    """Choose the notifier: Telegram when configured, else console or null, rate-limited."""
    from datetime import timedelta

    kind = cfg.kind
    has_token = secrets.has("kestrel_telegram_token") and bool(secrets.kestrel_telegram_chat_id)
    inner: Notifier
    if kind == "null":
        inner = NullNotifier()
    elif kind == "console":
        inner = ConsoleNotifier()
    elif kind == "telegram" or (kind == "auto" and has_token):
        if not has_token:
            log.warning("telegram_not_configured", note="falling back to NullNotifier")
            inner = NullNotifier()
        else:
            if transport is None:
                assert secrets.kestrel_telegram_token is not None
                transport = PtbTransport(secrets.kestrel_telegram_token.get_secret_value())
            inner = TelegramNotifier(transport, str(secrets.kestrel_telegram_chat_id))
    else:
        inner = NullNotifier()
    return RateLimitedNotifier(inner, window=timedelta(minutes=cfg.rate_limit_minutes), **({"clock": clock} if clock else {}))


# ----------------------------------------------------------------------------- bot commands


class StateReader(Protocol):
    """What the bot needs to read; implemented by the live state store."""

    def status(self) -> dict[str, Any]:
        """Last cycle, halt state, run id."""
        ...

    def equity_summary(self) -> dict[str, Any]:
        """Equity, PnL figures."""
        ...

    def positions(self) -> list[dict[str, Any]]:
        """Open positions."""
        ...

    def recent_trades(self, n: int) -> list[dict[str, Any]]:
        """Last ``n`` fills."""
        ...

    def last_signals(self) -> dict[str, float]:
        """Target weights from the last cycle."""
        ...

    def latest_report(self) -> Path | None:
        """Path of the latest HTML report."""
        ...


class CommandHandlers:
    """Pure command dispatch: ``handle(command, args, sender) -> reply text``."""

    def __init__(
        self,
        state: StateReader,
        *,
        allowed_chat_id: str,
        halt: Callable[[str], None],
        resume: Callable[[str], bool],
        display_tz: str = "Asia/Bangkok",
    ) -> None:
        """Create handlers bound to one allowed chat id."""
        self.state = state
        self.allowed = str(allowed_chat_id)
        self._halt = halt
        self._resume = resume
        self.tz = ZoneInfo(display_tz)
        self._warned: set[str] = set()

    def handle(self, command: str, args: list[str], sender_chat_id: str) -> str | tuple[str, Path] | None:
        """Dispatch a command. Unknown senders are ignored (logged once)."""
        if str(sender_chat_id) != self.allowed:
            if sender_chat_id not in self._warned:
                self._warned.add(sender_chat_id)
                log.warning("telegram_unknown_sender", chat_id=str(sender_chat_id))
            return None
        cmd = command.lstrip("/").lower()
        fn = getattr(self, f"cmd_{cmd}", None)
        if fn is None:
            return "Unknown command. Send /help."
        return fn(args)  # type: ignore[no-any-return]

    def _fmt_ts(self, iso: str | None) -> str:
        if not iso:
            return "-"
        return datetime.fromisoformat(iso).astimezone(self.tz).strftime("%Y-%m-%d %H:%M %Z")

    def cmd_help(self, args: list[str]) -> str:
        """List commands."""
        return (
            "/status  run, last cycle, halt state\n"
            "/equity  equity and PnL\n"
            "/positions  open positions\n"
            "/trades [n]  last n fills\n"
            "/signals  last target weights\n"
            "/halt <reason>  flatten and stop\n"
            "/resume <reason>  clear the halt (type the halt reason back)\n"
            "/report  latest HTML report\n"
            "/help"
        )

    def cmd_status(self, args: list[str]) -> str:
        """Run status."""
        s = self.state.status()
        halt = s.get("halt") or {}
        lines = [
            f"run: {s.get('run_id', '-')}",
            f"strategy: {s.get('strategy', '-')}  market: {s.get('market', '-')}",
            f"last cycle: {self._fmt_ts(s.get('last_cycle_ts'))}",
            f"last bar: {self._fmt_ts(s.get('last_bar_ts'))}",
            f"halted: {'yes (' + str(halt.get('reason')) + ')' if halt.get('halted') else 'no'}",
        ]
        return "\n".join(lines)

    def cmd_equity(self, args: list[str]) -> str:
        """Equity summary."""
        e = self.state.equity_summary()
        return (
            f"equity: {e.get('equity', 0):,.2f}\n"
            f"cash: {e.get('cash', 0):,.2f}\n"
            f"day pnl: {e.get('day_pnl', 0):+,.2f}\n"
            f"week pnl: {e.get('week_pnl', 0):+,.2f}\n"
            f"drawdown: {e.get('drawdown', 0):.2%}"
        )

    def cmd_positions(self, args: list[str]) -> str:
        """Open positions table."""
        rows = self.state.positions()
        if not rows:
            return "no open positions"
        lines = ["```", f"{'symbol':<12}{'qty':>12}{'value':>14}"]
        for r in rows[: MAX_LINES - 4]:
            lines.append(f"{r['symbol']:<12}{float(r['qty']):>12.4f}{float(r['market_value']):>14.2f}")
        lines.append("```")
        return "\n".join(lines)

    def cmd_trades(self, args: list[str]) -> str:
        """Recent fills."""
        n = int(args[0]) if args and args[0].isdigit() else 10
        rows = self.state.recent_trades(min(n, MAX_LINES - 4))
        if not rows:
            return "no trades yet"
        lines = ["```", f"{'time':<17}{'sym':<10}{'side':<5}{'qty':>10}{'px':>10}"]
        for r in rows:
            lines.append(
                f"{self._fmt_ts(r.get('ts'))[5:16]:<17}{r['symbol']:<10}{r['side']:<5}{float(r['qty']):>10.4f}{float(r['price']):>10.2f}"
            )
        lines.append("```")
        return "\n".join(lines)

    def cmd_signals(self, args: list[str]) -> str:
        """Last target weights."""
        sig = self.state.last_signals()
        if not sig:
            return "no signals yet"
        return "\n".join(f"{s}: {w:.1%}" for s, w in sorted(sig.items()))

    def cmd_halt(self, args: list[str]) -> str:
        """Halt with a reason."""
        reason = " ".join(args).strip()
        if not reason:
            return "usage: /halt <reason>"
        self._halt(reason)
        return f"halted: {reason}"

    def cmd_resume(self, args: list[str]) -> str:
        """Resume; the owner must type the halt reason back."""
        reason = " ".join(args).strip()
        if not reason:
            return "usage: /resume <reason>  (type the halt reason back to confirm)"
        if self._resume(reason):
            return "resumed"
        return "resume refused: reason does not match the active halt"

    def cmd_report(self, args: list[str]) -> str | tuple[str, Path]:
        """Latest HTML report."""
        p = self.state.latest_report()
        if p is None or not p.exists():
            return "no report yet"
        return ("latest report", p)


class PtbTransport:
    """``python-telegram-bot`` transport. Constructed only when a token exists."""

    def __init__(self, token: str) -> None:
        """Create the bot object (no network until a send)."""
        from telegram import Bot

        self._bot = Bot(token)

    def _run(self, coro: Any) -> None:
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(coro)
            return
        loop.create_task(coro)

    def send_message(self, chat_id: str, text: str) -> None:
        """Send text."""
        self._run(self._bot.send_message(chat_id=chat_id, text=text))

    def send_document(self, chat_id: str, path: Path, caption: str = "") -> None:
        """Send a file."""
        self._run(self._bot.send_document(chat_id=chat_id, document=str(path), caption=caption))


def run_bot(token: str, handlers: CommandHandlers) -> None:  # pragma: no cover - needs a real token
    """Long-poll Telegram and dispatch commands. Started by the owner through ``kestrel run``."""
    from telegram import Update
    from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

    async def _dispatch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or update.message.text is None:
            return
        parts = update.message.text.split()
        reply = handlers.handle(parts[0], parts[1:], str(update.message.chat_id))
        if reply is None:
            return
        if isinstance(reply, tuple):
            text, path = reply
            await update.message.reply_document(document=str(path), caption=text)
        else:
            await update.message.reply_text(reply)

    app = ApplicationBuilder().token(token).build()
    for name in ("status", "equity", "positions", "trades", "signals", "halt", "resume", "report", "help"):
        app.add_handler(CommandHandler(name, _dispatch))
    app.run_polling(drop_pending_updates=True)
