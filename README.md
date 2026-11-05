# kestrel

Backtest, validate, and paper-trade strategies across crypto and US equities,
and find out when your backtest is lying.

> Paper trading only. kestrel has no live-money mode and refuses non-paper endpoints.
> Nothing here is financial advice.

**Status: skeleton, untested.** Every module from the build spec exists under `src/kestrel/`, but
the build was stopped before anything was run. Read `PROGRESS.txt` first.

## Quickstart (intended; unverified)

Ubuntu bash:

```bash
uv sync --all-extras
uv run kestrel init
uv run kestrel backtest --config configs/quickstart_synthetic.yaml
```

Windows PowerShell:

```powershell
uv sync --all-extras
uv run kestrel init
uv run kestrel backtest --config configs/quickstart_synthetic.yaml
```

## Layout

See `docs/BUILD_LOG.md` for decisions and `docs/OWNER_TODO.md` for what the owner must do next.

## Licence

MIT.
