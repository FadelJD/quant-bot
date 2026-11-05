"""The kestrel CLI (typer + rich). Exit codes: 0 ok, 1 user error, 2 data error, 3 adapter error, 4 risk halt."""

from __future__ import annotations

import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from kestrel import __version__
from kestrel.errors import KestrelError

app = typer.Typer(help="Backtest, validate, and paper-trade strategies, and find out when a backtest is lying. Paper only.", no_args_is_help=True, rich_markup_mode="markdown")
data_app = typer.Typer(help="Fill and check the bar cache.")
strategies_app = typer.Typer(help="List strategies and print parameter schemas.")
state_app = typer.Typer(help="Inspect the live state store.")
app.add_typer(data_app, name="data")
app.add_typer(strategies_app, name="strategies")
app.add_typer(state_app, name="state")
console = Console()
err = Console(stderr=True)


def _fail(exc: KestrelError) -> None:
    err.print(f"[red]{type(exc).__name__}[/red]: {exc}")
    raise typer.Exit(code=exc.exit_code)


def _emit(obj: Any, as_json: bool) -> None:
    if as_json:
        console.print_json(json.dumps(obj, default=str))
    else:
        console.print(obj)


@app.callback()
def _root(version: bool = typer.Option(False, "--version", help="Print the version and exit.")) -> None:
    if version:
        console.print(f"kestrel {__version__}")
        raise typer.Exit()


# --------------------------------------------------------------------------- init / doctor


@app.command()
def init(path: Path = typer.Option(Path("."), help="Project directory.")) -> None:
    """Create configs/, .env, data/, state/ and write a doctor report.

    Example: `kestrel init`
    """
    base = path.resolve()
    for d in ("configs/universes", "data/cache", "state", "reports", "logs"):
        (base / d).mkdir(parents=True, exist_ok=True)
    pkg_configs = Path(__file__).resolve().parents[2] / "configs"
    if pkg_configs.exists():
        for src in pkg_configs.rglob("*.yaml"):
            dst = base / "configs" / src.relative_to(pkg_configs)
            if not dst.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(src, dst)
    env_example = Path(__file__).resolve().parents[2] / ".env.example"
    if env_example.exists() and not (base / ".env").exists():
        shutil.copy(env_example, base / ".env")
    if sys.version_info < (3, 11):
        err.print("[red]Python 3.11+ required[/red]")
        raise typer.Exit(code=1)
    console.print(f"initialised {base}")
    doctor(json_out=False)


@app.command()
def doctor(json_out: bool = typer.Option(False, "--json", help="Machine-readable output.")) -> None:
    """Report which optional keys are present, adapter reachability, cache size and disk space. Never prints key values.

    Example: `kestrel doctor`
    """
    from kestrel.config import Secrets
    from kestrel.data.cache import Manifest, ParquetCache

    secrets = Secrets()
    cache = ParquetCache(Path("data/cache"), Manifest(Path("data/manifest.json")))
    usage = shutil.disk_usage(Path.cwd())
    report: dict[str, Any] = {
        "version": __version__,
        "python": sys.version.split()[0],
        "secrets_present": secrets.presence(),
        "telegram_chat_id_set": bool(secrets.kestrel_telegram_chat_id),
        "cache_mb": round(cache.size_bytes() / 1e6, 2),
        "cached_series": len(cache.series()),
        "disk_free_gb": round(usage.free / 1e9, 1),
        "ml_extra": _importable("lightgbm"),
        "paper_endpoints": {"alpaca": "https://paper-api.alpaca.markets", "ccxt": "sandbox via set_sandbox_mode(True)"},
        "ai_tokens_this_month": _llm_tokens(),
    }
    if json_out:
        _emit(report, True)
        return
    t = Table(title="kestrel doctor")
    t.add_column("check")
    t.add_column("value")
    for k, v in report.items():
        t.add_row(k, json.dumps(v) if isinstance(v, dict | list) else str(v))
    console.print(t)


def _importable(mod: str) -> bool:
    try:
        __import__(mod)
    except Exception:  # noqa: BLE001
        return False
    return True


def _llm_tokens() -> int:
    db = Path("state/kestrel.db")
    if not db.exists():
        return 0
    from kestrel.live.state import StateStore

    store = StateStore(db)
    try:
        now = datetime.now(tz=UTC)
        return store.llm_tokens_since(now.replace(day=1, hour=0, minute=0, second=0, microsecond=0))
    finally:
        store.close()


# --------------------------------------------------------------------------- data


@data_app.command("fetch")
def data_fetch(
    market: str = typer.Option("crypto", help="crypto or equities"),
    universe: str = typer.Option("crypto_top20"),
    timeframe: str = typer.Option("1d"),
    from_: str = typer.Option("2022-01-01", "--from"),
    to: str | None = typer.Option(None, "--to"),
    source: str = typer.Option("ccxt", help="ccxt | alpaca | yfinance | fixtures | synthetic"),
) -> None:
    """Fill the cache for a universe.

    Example: `kestrel data fetch --market crypto --universe crypto_top20 --timeframe 1d --from 2022-01-01`
    """
    from kestrel.config import DataConfig, Secrets
    from kestrel.data.service import DataService
    from kestrel.data.universe import load_universe

    try:
        cfg = DataConfig(source=source)  # type: ignore[arg-type]
        uni = load_universe(universe)
        secrets = Secrets()
        key = None
        if secrets.apca_api_key_id and secrets.apca_api_secret_key:
            key = (secrets.apca_api_key_id.get_secret_value(), secrets.apca_api_secret_key.get_secret_value())
        svc = DataService.from_config(cfg, market, alpaca_key=key)
        start = datetime.fromisoformat(from_).replace(tzinfo=UTC)
        end = datetime.fromisoformat(to).replace(tzinfo=UTC) if to else datetime.now(tz=UTC)
        frames = svc.get_universe_bars(uni.symbols, timeframe, start, end)
    except KestrelError as exc:
        _fail(exc)
        return
    for s, f in frames.items():
        console.print(f"{s}: {len(f)} bars {f.index[0]:%Y-%m-%d} to {f.index[-1]:%Y-%m-%d}")


@data_app.command("check")
def data_check(json_out: bool = typer.Option(False, "--json")) -> None:
    """Validate cache integrity and print gaps.

    Example: `kestrel data check`
    """
    from kestrel.config import DataConfig
    from kestrel.data.service import DataService

    svc = DataService.from_config(DataConfig(source="synthetic"), "crypto")
    rows = svc.check()
    if json_out:
        _emit(rows, True)
        return
    t = Table(title="cache check")
    for c in ("market", "symbol", "timeframe", "rows", "first", "last", "status", "detail"):
        t.add_column(c)
    for r in rows:
        t.add_row(*[str(r[c]) for c in ("market", "symbol", "timeframe", "rows", "first", "last", "status", "detail")])
    console.print(t)


# --------------------------------------------------------------------------- backtest / validate / sweep / report


def _load(config: Path, strategy: str | None, from_: str | None, to: str | None) -> Any:
    from kestrel.config import load_run_config

    cfg = load_run_config(config)
    if strategy:
        cfg.strategy.name = strategy
    if from_:
        cfg.backtest.start = datetime.fromisoformat(from_).date()
    if to:
        cfg.backtest.end = datetime.fromisoformat(to).date()
    return cfg


def _summary_table(metrics: dict[str, Any], title: str) -> Table:
    t = Table(title=title)
    t.add_column("metric")
    t.add_column("value", justify="right")
    for k in ("total_return", "cagr", "sharpe", "sortino", "max_drawdown", "calmar", "n_trades", "hit_rate", "turnover_annual", "fees_pct_of_gross_pnl", "clamped_shorts"):
        v = metrics.get(k)
        t.add_row(k, f"{v:.4f}" if isinstance(v, float) else str(v))
    return t


@app.command()
def backtest(
    config: Path = typer.Option(..., "--config"),
    strategy: str | None = typer.Option(None, "--strategy"),
    from_: str | None = typer.Option(None, "--from"),
    to: str | None = typer.Option(None, "--to"),
    enforce_halts: bool = typer.Option(False, "--enforce-halts", help="Flatten and stop on risk breaches as the live loop would."),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Run one backtest; writes reports/<run_id>/report.html and metrics.json.

    Example: `kestrel backtest --config configs/backtest_crypto.yaml --strategy sma_cross`
    """
    from kestrel.backtest.runner import run_backtest
    from kestrel.reporting.export import write_metrics_json
    from kestrel.reporting.html import render_report

    try:
        cfg = _load(config, strategy, from_, to)
        res = run_backtest(cfg, enforce_halts=enforce_halts)
        out = Path(cfg.reports_dir) / res.run_id
        render_report(res, out / "report.html", display_tz=cfg.display_tz)
        write_metrics_json(res, out / "metrics.json")
    except KestrelError as exc:
        _fail(exc)
        return
    if json_out:
        _emit({"run_id": res.run_id, "report": str(out / "report.html"), "metrics": res.metrics}, True)
        return
    console.print(_summary_table(res.metrics, f"{res.strategy} {res.run_id}"))
    console.print(f"report: {out / 'report.html'}")


@app.command()
def validate(
    config: Path = typer.Option(..., "--config"),
    strategy: str | None = typer.Option(None, "--strategy"),
    n_trials: int | None = typer.Option(None, "--n-trials", help="Variants tried, for the deflated Sharpe."),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Run the full validation suite and write the verdict next to the report.

    Example: `kestrel validate --config configs/backtest_crypto.yaml`
    """
    from kestrel.backtest.runner import load_frames, run_backtest
    from kestrel.reporting.export import write_metrics_json
    from kestrel.reporting.html import render_report
    from kestrel.validation.runner import run_validation

    try:
        cfg = _load(config, strategy, None, None)
        frames = load_frames(cfg)
        res = run_backtest(cfg, frames=frames)
        rep = run_validation(cfg, frames, result=res, n_trials=n_trials)  # type: ignore[arg-type]
        out = Path(cfg.reports_dir) / res.run_id
        rep.save(out / "validation.json")
        render_report(res, out / "report.html", validation=json.loads(rep.to_json()), display_tz=cfg.display_tz)
        write_metrics_json(res, out / "metrics.json", validation=json.loads(rep.to_json()))
    except KestrelError as exc:
        _fail(exc)
        return
    if json_out:
        console.print_json(rep.to_json())
        return
    colour = {"pass": "green", "caution": "yellow", "fail": "red"}[rep.verdict]
    console.print(f"[{colour}]verdict: {rep.verdict}[/{colour}]")
    for r in rep.reasons:
        console.print(f"  - {r}")
    console.print(f"report: {out / 'report.html'}")


@app.command()
def sweep(
    config: Path = typer.Option(..., "--config"),
    param: list[str] = typer.Option(..., "--param", help="name=start:stop:step (inclusive), repeatable."),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Grid run over parameters; writes a sensitivity table (CSV) and prints it.

    Example: `kestrel sweep --config configs/backtest_crypto.yaml --param fast=5:30:5 --param slow=50:200:25`
    """
    import itertools

    from kestrel.backtest.runner import load_frames, run_backtest

    try:
        cfg = _load(config, None, None, None)
        frames = load_frames(cfg)
        axes: dict[str, list[float]] = {}
        for p in param:
            name, rng = p.split("=")
            lo, hi, st = (float(x) for x in rng.split(":"))
            vals = []
            v = lo
            while v <= hi + 1e-9:
                vals.append(int(v) if float(v).is_integer() else v)
                v += st
            axes[name] = vals
        rows = []
        for combo in itertools.product(*axes.values()):
            c = cfg.model_copy(deep=True)
            c.strategy.params = {**cfg.strategy.params, **dict(zip(axes, combo, strict=True))}
            try:
                res = run_backtest(c, frames=frames)
                rows.append({**dict(zip(axes, combo, strict=True)), "sharpe": res.metrics["sharpe"], "max_drawdown": res.metrics["max_drawdown"], "n_trades": res.metrics["n_trades"]})
            except KestrelError as exc:
                rows.append({**dict(zip(axes, combo, strict=True)), "error": str(exc)})
    except KestrelError as exc:
        _fail(exc)
        return
    out = Path(cfg.reports_dir) / "sweeps"
    out.mkdir(parents=True, exist_ok=True)
    import csv

    path = out / f"sweep-{cfg.strategy.name}-{datetime.now(tz=UTC):%Y%m%dT%H%M%SZ}.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=sorted({k for r in rows for k in r}))
        w.writeheader()
        w.writerows(rows)
    if json_out:
        _emit(rows, True)
        return
    t = Table(title="sweep")
    cols = [*axes, "sharpe", "max_drawdown", "n_trades"]
    for c in cols:
        t.add_column(c)
    for r in rows:
        t.add_row(*[f"{r.get(c, ''):.3f}" if isinstance(r.get(c), float) else str(r.get(c, "")) for c in cols])
    console.print(t)
    console.print(f"written: {path}  (n_trials for validate: {len(rows)})")


@app.command()
def report(run_id: str = typer.Option(..., "--run-id"), reports_dir: Path = typer.Option(Path("reports"))) -> None:
    """Regenerate the HTML report from a run's metrics.json (requires a re-run for the curve).

    Example: `kestrel report --run-id sma_cross-crypto-20220101-20251231-abcd1234`
    """
    path = reports_dir / run_id / "metrics.json"
    if not path.exists():
        err.print(f"[red]no metrics.json for run {run_id}[/red]")
        raise typer.Exit(code=1)
    console.print(f"report for {run_id} lives at {reports_dir / run_id / 'report.html'}; re-run `kestrel backtest` with the same config to regenerate the curve.")


# --------------------------------------------------------------------------- run / halt / resume / state


@app.command()
def run(
    config: Path = typer.Option(..., "--config"),
    i_understand_this_is_overfit: bool = typer.Option(False, "--i-understand-this-is-overfit", help="Start even if the last validation verdict was fail."),
) -> None:
    """Start the paper loop in the foreground (supervision is external; see docs/runbook.md).

    Example: `kestrel run --config configs/paper_crypto.yaml`
    """
    from kestrel.clock import RealClock
    from kestrel.config import Secrets, load_run_config
    from kestrel.data.universe import load_universe
    from kestrel.execution.mock_adapter import MockAdapter
    from kestrel.live.lock import InstanceLock
    from kestrel.live.runner import LiveRunner
    from kestrel.live.state import StateStore
    from kestrel.logsetup import configure_logging
    from kestrel.notify.telegram import build_notifier
    from kestrel.strategies.base import build_strategy
    from kestrel.validation.runner import ValidationReport

    try:
        cfg = load_run_config(config)
        configure_logging(Path("logs"))
        secrets = Secrets()
        # Refuse a strategy whose last validation verdict was fail.
        verdicts = sorted(Path(cfg.reports_dir).glob(f"{cfg.strategy.name}-{cfg.market}-*/validation.json"))
        if verdicts:
            last = ValidationReport.load(verdicts[-1])
            if last.verdict == "fail" and not i_understand_this_is_overfit:
                raise KestrelError(f"last validation verdict for {cfg.strategy.name} is FAIL ({verdicts[-1]}); pass --i-understand-this-is-overfit to override")
            if last.verdict == "fail":
                err.print("[bold red]WARNING: starting a strategy whose validation verdict is FAIL (override flag given)[/bold red]")
        uni = load_universe(cfg.universe, cfg.universe_dir)
        clock = RealClock()
        strategy = build_strategy(cfg.strategy.name, cfg.strategy.params, timeframe=cfg.timeframe, universe=cfg.universe)
        adapter: Any
        if cfg.adapter.kind == "alpaca":
            from kestrel.execution.alpaca_adapter import AlpacaAdapter

            if not (secrets.apca_api_key_id and secrets.apca_api_secret_key):
                raise KestrelError("APCA_API_KEY_ID and APCA_API_SECRET_KEY are required for the alpaca adapter")
            adapter = AlpacaAdapter(secrets.apca_api_key_id.get_secret_value(), secrets.apca_api_secret_key.get_secret_value(), market=cfg.market)
        elif cfg.adapter.kind == "ccxt":
            from kestrel.execution.ccxt_adapter import CcxtAdapter

            if not (secrets.kestrel_ccxt_api_key and secrets.kestrel_ccxt_secret):
                raise KestrelError("KESTREL_CCXT_API_KEY and KESTREL_CCXT_SECRET are required for the ccxt adapter")
            adapter = CcxtAdapter(cfg.adapter.exchange, secrets.kestrel_ccxt_api_key.get_secret_value(), secrets.kestrel_ccxt_secret.get_secret_value())
        else:
            from kestrel.data.service import DataService

            svc = DataService.from_config(cfg.data, cfg.market)

            def feed(symbol: str, ts: datetime) -> float:
                f = svc.get_bars(symbol, cfg.timeframe, ts - timedelta(days=5), ts)
                return float(f["close"].iloc[-1])

            from datetime import timedelta

            adapter = MockAdapter(market=cfg.market, clock=clock, price_feed=feed, initial_cash=cfg.backtest.initial_cash)
        store = StateStore(cfg.live.state_dir / "kestrel.db", config_key=str(config))
        notifier = build_notifier(cfg.notify, secrets)
        run_id = f"{cfg.strategy.name}-{cfg.market}-paper-{cfg.adapter.kind}"
        runner = LiveRunner(cfg, strategy=strategy, adapter=adapter, clock=clock, store=store, notifier=notifier, symbols=uni.symbols, run_id=run_id)
        with InstanceLock(cfg.live.state_dir / f"{config.stem}.lock"):
            runner.start()
            console.print(f"paper loop started: {run_id}; adapter {adapter.name}; notifier {notifier.name}. Ctrl+C to stop.")
            runner.run_forever()
    except KeyboardInterrupt:
        console.print("stopped")
    except KestrelError as exc:
        _fail(exc)


def _store(state_dir: Path, config: Path | None) -> Any:
    from kestrel.live.state import StateStore

    return StateStore(state_dir / "kestrel.db", config_key=str(config) if config else "default")


@app.command()
def halt(reason: str = typer.Option(..., "--reason"), state_dir: Path = typer.Option(Path("state")), config: Path | None = typer.Option(None, "--config")) -> None:
    """Set the halt flag through the state store (the running loop flattens on its next cycle).

    Example: `kestrel halt --reason "manual stop"`
    """
    store = _store(state_dir, config)
    store.set_halt(True, reason, datetime.now(tz=UTC))
    console.print(f"halt flag set: {reason}")


@app.command()
def resume(state_dir: Path = typer.Option(Path("state")), config: Path | None = typer.Option(None, "--config")) -> None:
    """Clear the halt flag.

    Example: `kestrel resume`
    """
    store = _store(state_dir, config)
    store.set_halt(False, "", None)
    console.print("halt flag cleared")


@state_app.command("show")
def state_show(state_dir: Path = typer.Option(Path("state")), config: Path | None = typer.Option(None, "--config"), json_out: bool = typer.Option(False, "--json")) -> None:
    """Print positions, cash, last cycle and halt status.

    Example: `kestrel state show`
    """
    store = _store(state_dir, config)
    payload = {"status": store.status(), "equity": store.equity_summary(), "positions": store.positions(), "signals": store.last_signals()}
    if json_out:
        _emit(payload, True)
        return
    console.print(payload)


# --------------------------------------------------------------------------- strategies


@strategies_app.command("list")
def strategies_list(json_out: bool = typer.Option(False, "--json")) -> None:
    """List registered strategies.

    Example: `kestrel strategies list`
    """
    from kestrel.strategies import STRATEGIES

    rows = [{"name": n, "description": c.description} for n, c in sorted(STRATEGIES.items())]
    if json_out:
        _emit(rows, True)
        return
    t = Table(title="strategies")
    t.add_column("name")
    t.add_column("description")
    for r in rows:
        t.add_row(r["name"], r["description"])
    console.print(t)


@strategies_app.command("schema")
def strategies_schema(name: str) -> None:
    """Print the parameter schema (JSON) for a strategy.

    Example: `kestrel strategies schema sma_cross`
    """
    from kestrel.strategies import STRATEGIES

    if name not in STRATEGIES:
        err.print(f"[red]unknown strategy {name}[/red]; try: {', '.join(sorted(STRATEGIES))}")
        raise typer.Exit(code=1)
    console.print_json(json.dumps(STRATEGIES[name].schema()))


if __name__ == "__main__":  # pragma: no cover
    app()
