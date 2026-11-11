# 04c · Documentation set

Created 2026-11-11 · Wave 4 · Parallel with 04a, 04b · Needs wave 3 handoff notes · Spec sections 3, 19, 20

## Goal

Documentation good enough for a professional technical writer to put his name on: a stranger
reaches a passing backtest in five minutes, and the owner can operate the bot six months from now.

## Owns

`README.md`, `docs/ARCHITECTURE.md`, `docs/KNOWLEDGE_BASE.md`, `docs/strategies.md`,
`docs/runbook.md`, `docs/thailand.md`, `docs/integrations.md`, `docs/img/`.

## Current state

Stubs. The README is a handover note. Provider facts are scattered across wave 2 and 3 handoff notes.

## Style, applied everywhere

AU/UK spelling. No exclamation marks, no emoji in the final docs. Every shell snippet in
PowerShell and bash. Every command shown with its expected first line of output, produced by
actually running it. No financial advice.

## Work items

1. **README**, following spec section 19 exactly: tagline, paper-only notice, Why (three
   sentences), Quickstart (five minutes, no accounts, both shells), What it does (verdict banner
   screenshot from 03c), Paper trading, From Thailand, Writing a strategy (the protocol in 15
   lines, from 02b's template), Optional integrations, Architecture (diagram), Development,
   Roadmap, Licence. A short personal note at the end drafted in the owner's voice and clearly
   marked for his edit.
2. **Quickstart proof.** Run every README block in a fresh clone inside a clean directory on
   Linux; for PowerShell, run under `pwsh` if available in the container, otherwise record that
   the Windows CI job covers it (add a CI step in coordination with 04b that executes the
   quickstart block on `windows-latest`).
3. **ARCHITECTURE.md.** The pipeline and the four side services, the import rules and why, the
   contract list (link to CONTRACTS), the loop order of a backtest bar and a live cycle side by
   side, state store schema, where Decimal and float meet. `docs/img/architecture.svg` drawn by
   hand as an SVG file (no external tool needed), legible in light and dark themes.
4. **KNOWLEDGE_BASE.md.** Spec section 20 expanded, one short worked example per item with real
   numbers produced by this codebase where possible: lookahead, survivorship, overfitting and
   selection, costs (the 0.1% daily turnover arithmetic), liquidity, regime dependence,
   operational failure; why regression on prices fails; each validation method in one paragraph
   with its formula; market mechanics table; risk vocabulary with the formula used in `metrics.py`;
   reading list with a one-line takeaway each. Mark Kelly and VaR as documented, not implemented.
   Explain the additions I1 to I4 where they belong.
5. **strategies.md.** One page per strategy: hypothesis, parameters with defaults and sane
   ranges (generated from the schema so they cannot drift), regimes where it should and should
   not work, known failure modes. No hype. State plainly that the reference strategies exist to
   exercise the system and most will be marked `caution` or `fail` on real data.
6. **runbook.md.** Start, stop, restart, upgrade. Supervision three ways with the files from 04b.
   Halt and resume from CLI and Telegram. What each alert means and what to do. Reading the logs.
   Backing up and restoring state. Topping up testnet balances per exchange. The rehearsal
   command as the first thing to run. A troubleshooting table keyed by exit code and error text.
7. **thailand.md.** Each row of the spec's table verified against the provider's current
   documentation, with the URL and the date checked: Binance and Bybit testnets, OKX demo, public
   history endpoints, Alpaca paper availability, Bitkub public API, hosting, time zones (NYSE open
   in Bangkok time across US daylight saving), and the regulatory note as a written warning, not
   advice. Where the build container could not reach a provider's site, say so and list it as an
   owner check.
8. **integrations.md.** What each optional integration adds, what it costs, what happens without
   it, the data boundary (what a model may see), and how to add a provider or news source in under
   50 lines.
9. **Consistency pass.** One glossary (spec section 21) linked from every doc. Command names,
   flags and file paths checked against `kestrel --help` output by a small script, so docs cannot
   reference a flag that does not exist. Internal links checked.
10. **Screenshots.** `docs/img/report_verdict.png` and `report_mobile.png` from 03c, plus one of
    `kestrel validate` terminal output.

## Done when

- A fresh clone reaches a passing `kestrel backtest` on fixtures by following the README alone.
- Every command and flag mentioned in the docs exists (script output attached to the handoff note).
- Every provider claim carries a URL and a date, or is listed as an owner check.
- No stub files remain under `docs/`.

## Out of scope

A docs website. API reference generation. Translations.
