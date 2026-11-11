# 03e · Optional integrations (AI narrative, news)

Created 2026-11-11 · Wave 3 · Parallel with 03a to 03d · Needs 02g · Spec section 15

## Goal

Two optional extras that explain and summarise, never decide, cost nothing unless switched on,
and vanish without a trace when no key is present.

## Owns

`src/kestrel/integrations/`.

## Current state

`llm.py` has a client protocol, Anthropic and OpenAI clients over `httpx`, and a budgeted
`Narrator`. `news.py` has a protocol and one source. Neither has been called.

## Work items

1. **Absent means absent.** With no key or `enabled: false`: no CLI commands registered (04a
   asks `integrations.available()`), no report section, no log noise, no error.
2. **Provider clients.** Verify request and response shapes against current provider docs; record
   URL and date. Model ids are config, with defaults checked at build time against the provider's
   published list (do not trust the ids in the skeleton). Anthropic first, OpenAI second.
   Timeouts 60 s, one retry on 429 or 5xx with backoff, then give up.
3. **What the model may see.** Aggregates only: the metrics JSON, the verdict and reasons,
   position symbols with weights and PnL, counts of warnings. Never keys, account ids, order ids,
   or the raw trade log. Implement this as one `build_payload()` function with an allowlist of
   fields, so the boundary is in one place and reviewable.
4. **Budget.** Monthly token cap (default 200 000) counted in the state store through the
   `UsageStore` protocol. Stop calling at the cap. Emit `budget_80pct` once per month. Every call
   logged with input and output tokens.
5. **Estimated spend.** A small price table in config (`usd_per_million_input`,
   `usd_per_million_output` per model, owner-editable) so `kestrel doctor` can print an estimate.
   Do not hard-code prices as facts; label the output as an estimate from the configured table.
6. **Degrade gracefully.** Any provider failure returns `None`; the caller writes the non-AI
   report and one warning line.
7. **Three uses.** Daily and weekly narrative from metrics; `kestrel explain --run-id`;
   `kestrel strategies describe X` (drafts a `docs/strategies.md` page from code and docstrings
   for the owner to edit). Each is a function here; 04a registers the commands.
8. **Prompting.** One system prompt: plain language, state numbers as given, no recommendations,
   no financial advice, AU/UK spelling, a word limit. Add an output check that rejects text
   containing an imperative to buy or sell and falls back to the non-AI report.
9. **News.** `NewsSource` protocol, one implementation behind `KESTREL_NEWS_API_KEY`, headlines
   attached to the daily report for context only. Free tier, documented limits, cached per day.
   Never a signal: `import-linter` already forbids strategies and risk from importing this package.
10. **Extension guide.** The exact steps to add a provider or a news source in under 50 lines
    (handoff note for 04c's `docs/integrations.md`).

## Done when

- With no keys, the smoke gate shows no AI or news commands and reports have no such section.
- With a fake `httpx` transport, a narrative is produced, usage is recorded, the cap stops calls,
  and a failing provider yields the plain report with one warning.
- The payload allowlist is the only path from run data to a provider.

## Out of scope

Agents, tool use, signals from text, real provider calls from the build agent, tests.
