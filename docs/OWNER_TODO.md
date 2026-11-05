# Owner TODO

Decisions and actions that are the owner's to make. The agent continued with the default each time.

- [ ] 2026-11-05: Confirm the name `kestrel`. Default used: `kestrel`.
- [ ] 2026-11-05: Branch model. The spec says `develop` + `feat/*`; this session was required to push to `claude/new-session-u3eief`. Create `develop` from it (`git branch develop claude/new-session-u3eief && git push -u origin develop`).
- [ ] 2026-11-05: Market data hosts are blocked from the build container. Run `uv run python scripts/fetch_fixtures.py` locally to replace the synthetic fixtures with real Binance (and, with an Alpaca paper key, IEX) bars.
- [ ] 2026-11-05: Confirm the 20 crypto pairs and 30 US tickers in `configs/universes/`.
- [ ] 2026-11-05: Choose the first paper account (Alpaca or a CCXT testnet). Both adapters are built; pick at run time via `adapter.kind`.
- [ ] 2026-11-05: AI provider preference. Default: Anthropic first, OpenAI second, both optional and off.
- [ ] 2026-11-05: Hosting for the unattended run (home PC or Singapore VPS). No deployment performed.
- [ ] 2026-11-05: The build was stopped before testing. Nothing in `src/` has been executed yet; see `PROGRESS.txt`.
