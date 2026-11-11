# 02f · Notifiers and the Telegram bot

Created 2026-11-11 · Wave 2 · Parallel with 02a to 02e, 02g · Needs 01 · Spec sections 14 and 16

## Goal

Alerts reach the owner's phone, the bot answers read-only questions and two state changes
(`/halt`, `/resume`), and none of it can crash or block the trading loop.

## Owns

`src/kestrel/notify/`.

## Current state

`Notifier` protocol, null and console notifiers, a per-type rate limiter, `TelegramNotifier`,
`CommandHandlers` with nine commands, a recording transport and a PTB transport exist. Defect D12.

## Work items

1. **Transport (D12).** Replace per-message `asyncio.run` with a small background worker: one
   thread owning one event loop and a bounded queue. `send_message` and `send_document` enqueue
   and return. Failures are logged and dropped after two retries. `close()` drains with a timeout.
   The loop never waits on Telegram.
2. **Bot runner.** `TelegramBot.start()` runs PTB long polling in the same background thread and
   dispatches to `CommandHandlers`. `stop()` shuts it down. No webhook. The agent never starts it
   against a real token; the transport and the update source are both injectable.
3. **Authorisation.** Only `KESTREL_TELEGRAM_CHAT_ID` is served. Every other sender is ignored and
   logged once per chat id. Compare as strings.
4. **Commands.** `/status`, `/equity`, `/positions`, `/trades [n]`, `/signals`, `/halt <reason>`,
   `/resume <reason>`, `/report`, `/help`. No command places an order. `/resume` succeeds only when
   the typed text matches the active halt reason.
5. **Formatting.** Plain text. Tables in a fixed-width block. Hard cap of 40 lines and Telegram's
   4 096 characters: truncate with a final `...` line. Times shown in `display_tz`. Numbers with
   thousands separators.
6. **Alert types and severity.** `halt` critical; `reconcile_drift`, `adapter_error_streak`,
   `stale_data` warning; `daily_report`, `weekly_report`, `budget_80pct` info. Add `dead_man`
   (critical) and `parity_drift` (warning) for I6 and I4.
7. **Rate limiting.** One alert per type per 15 minutes except `halt` and `dead_man`. Suppressed
   alerts are counted and the next delivered alert of that type says how many were dropped.
8. **Selection.** `build_notifier(cfg, secrets)`: Telegram when a token and chat id exist, else
   `NullNotifier`; `console` on request. A `CompositeNotifier` sends to console and Telegram
   together so alerts are always in the log.
9. **State access.** Handlers read through the `StateReader` protocol only. The halt and resume
   callbacks are injected, so this package never imports `live/`.
10. **Report delivery.** `/report` sends the latest HTML as a document; files over Telegram's
    50 MB cap cannot occur (reports are under 5 MB) but check and say so if missing.

## Done when

- A scratch script drives every command through `CommandHandlers` with the recording transport.
- An unknown chat id gets no reply.
- With no token, `build_notifier` returns a notifier whose `send` is a no-op and nothing raises.
- D12 notifier half closed. Static checks pass on owned files.

## Out of scope

Starting the bot inside `kestrel run` (03b wires it). Email or other channels. Tests.
