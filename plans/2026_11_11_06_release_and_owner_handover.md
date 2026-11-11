# 06 · Release 0.1.0 and owner handover

Created 2026-11-11 · Wave 6 · Serial, one agent · Needs wave 5 green · Spec section 18 (milestone 14)

## Goal

Tag 0.1.0, prove the wheel works for someone who has never seen the repo, and hand the owner an
exact, short list of what only he can do. Then stop.

## Owns

`CHANGELOG.md`, version strings, `docs/OWNER_TODO.md` (final form), `docs/BUILD_LOG.md` (final
entries), `PROGRESS.txt` (delete or replace with a pointer), the release tag.

## Work items

1. **Pre-release audit.** Every defect D01 to D25 closed or explicitly deferred with a reason.
   Every addition I1 to I10 either shipped or listed under "not in 0.1.0". Spec coverage table in
   plan 00 section 10 re-checked line by line; gaps listed honestly.
2. **Paper-only audit.** Grep the tree for `live`, `api.alpaca.markets`, `api.binance.com` and
   similar; confirm each hit is in the deny list, a doc warning, or a test. Confirm there is no
   flag, env var or config path to a live endpoint. Record the grep output.
3. **Secrets audit.** `detect-secrets` clean; `.env` ignored; `git log -p` scanned for key-like
   strings across the whole history.
4. **Version and changelog.** `0.1.0` in `pyproject.toml` and `__init__.py`. `CHANGELOG.md` in
   Keep a Changelog format, written for a user, grouped by Added and Known limitations.
5. **Build and install proof.** `uv build`; install the wheel with `pipx` in a clean environment;
   run the README quickstart in an empty folder; attach the terminal output to the handoff note.
   Repeat on Windows through the CI job.
6. **Performance record.** The spec workload timing and the validation timing, final numbers in
   `BUILD_LOG.md`.
7. **Merge and tag.** PR `develop` → `main`; after green CI, tag `v0.1.0` on `main`; the release
   workflow attaches the wheel and sdist. Requires the owner's go-ahead to merge to `main` if
   branch protection is on; otherwise record that the tag was created by the agent.
8. **Final `OWNER_TODO.md`.** Exactly what the owner must do to start a paper run, in order:
   1. Create the paper account (Alpaca) or the testnet key (Binance or Bybit).
   2. Set the environment variables (names listed, never values).
   3. `kestrel doctor`.
   4. `kestrel run --rehearse 7d` and read the summary.
   5. `kestrel validate --config ...`.
   6. `kestrel run --config ...` under his chosen supervisor.
   Plus the open decisions from spec section 21 with the default taken for each, the provider
   facts that could not be verified from the build environment, and the real-fixture fetch.
9. **Roadmap note.** v2 candidates in the README: shorting, point-in-time universes, more
   adapters, Bitkub, combinatorial purged CV, correlation-aware sizing.
10. **Stop.** Do not start the paper loop. Do not create accounts. Do not deploy.

## Done when

- `v0.1.0` is tagged on `main` with a GitHub release carrying the wheel.
- The wheel installs with `pipx` and the quickstart passes in an empty folder on both OSes.
- `OWNER_TODO.md` is complete, dated, and contains nothing the agent could have done itself.
- The four spec success criteria are each marked met, or not met with the reason (the 7-day real
  paper run is the owner's and is listed as such).
