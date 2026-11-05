"""Self-contained HTML report (Jinja2 + Plotly, offline, responsive). Verdict banner first."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from jinja2 import Environment, PackageLoader, select_autoescape

from kestrel.backtest.engine import BacktestResult
from kestrel.reporting.metrics import monthly_returns

_env = Environment(loader=PackageLoader("kestrel.reporting", "templates"), autoescape=select_autoescape(["html"]))


def _fig_html(fig: Any, include_js: bool) -> str:
    return str(fig.to_html(full_html=False, include_plotlyjs="cdn" if False else (True if include_js else False), config={"responsive": True}))


def build_figures(result: BacktestResult, validation: dict[str, Any] | None) -> list[tuple[str, str]]:
    """Plotly figures as HTML snippets; plotly.js is embedded once, in the first figure."""
    import plotly.graph_objects as go

    figs: list[tuple[str, Any]] = []
    curve = result.equity_curve
    if not curve.empty:
        f = go.Figure()
        f.add_trace(go.Scatter(x=curve.index, y=curve["equity"], name="equity", line={"color": "#2563eb"}))
        f.add_trace(go.Scatter(x=curve.index, y=curve["equity"] * (1 + curve["drawdown"]) , name="peak-adjusted", line={"width": 0}, showlegend=False))
        f.add_trace(go.Scatter(x=curve.index, y=curve["drawdown"], name="drawdown", yaxis="y2", fill="tozeroy", line={"color": "#dc2626", "width": 1}))
        f.update_layout(title="Equity and drawdown", yaxis2={"overlaying": "y", "side": "right", "tickformat": ".0%"}, margin={"l": 40, "r": 40, "t": 50, "b": 40}, height=420)
        figs.append(("Equity curve", f))
        mr = monthly_returns(curve["equity"])
        if not mr.empty:
            h = go.Figure(data=go.Heatmap(z=mr.to_numpy(), x=[str(c) for c in mr.columns], y=[str(i) for i in mr.index], colorscale="RdYlGn", zmid=0, text=mr.round(3).to_numpy(), texttemplate="%{text:.1%}"))
            h.update_layout(title="Monthly returns", height=320, margin={"l": 40, "r": 40, "t": 50, "b": 40})
            figs.append(("Monthly returns", h))
    if validation:
        sens = validation.get("sensitivity") or {}
        axes = sens.get("axes") or []
        pts = sens.get("points") or []
        if len(axes) == 2 and pts:
            xs = sorted({p["params"][axes[0]] for p in pts})
            ys = sorted({p["params"][axes[1]] for p in pts})
            z = [[next((p["sharpe"] for p in pts if p["params"][axes[0]] == x and p["params"][axes[1]] == y), None) for x in xs] for y in ys]
            s = go.Figure(data=go.Heatmap(z=z, x=[str(x) for x in xs], y=[str(y) for y in ys], colorscale="Viridis"))
            s.update_layout(title=f"Parameter sensitivity (Sharpe): {axes[0]} x {axes[1]}", height=320, margin={"l": 40, "r": 40, "t": 50, "b": 40})
            figs.append(("Parameter sensitivity", s))
    out: list[tuple[str, str]] = []
    for i, (title, fig) in enumerate(figs):
        out.append((title, _fig_html(fig, include_js=i == 0)))
    return out


def render_report(result: BacktestResult, path: Path, *, validation: dict[str, Any] | None = None, manifest: dict[str, Any] | None = None, display_tz: str = "Asia/Bangkok") -> Path:
    """Render the report to ``path``. Returns the path."""
    tpl = _env.get_template("report.html.j2")
    curve = result.equity_curve
    trades = result.trades.copy()
    if not trades.empty:
        for col in ("ts_signal", "ts_fill"):
            trades[col] = pd.to_datetime(trades[col], utc=True).dt.tz_convert(display_tz).dt.strftime("%Y-%m-%d %H:%M")
    html = tpl.render(
        result=result,
        metrics=result.metrics,
        validation=validation,
        figures=build_figures(result, validation),
        trades=trades.to_dict("records")[:500],
        n_bars=len(curve),
        manifest=manifest or {},
        generated_at=datetime.now(tz=UTC).isoformat(timespec="seconds"),
        display_tz=display_tz,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path


def render_live_report(runner: Any) -> Path | None:  # pragma: no cover - thin wrapper
    """Render a report from a live runner's equity history (metrics only, no validation)."""
    from kestrel.reporting.metrics import compute_metrics

    curve = runner.equity_curve()
    if curve.empty:
        return None
    curve["exposure"] = 0.0
    curve["drawdown"] = curve["equity"] / curve["equity"].cummax() - 1.0
    curve["n_positions"] = 0
    trades = pd.DataFrame(runner.store.recent_trades(10_000))
    metrics = compute_metrics(curve, trades if not trades.empty else pd.DataFrame(), per_year=runner.cfg.annualisation, initial_cash=float(curve["equity"].iloc[0]))
    result = BacktestResult(runner.run_id, runner.strategy.name, runner.strategy.params.model_dump(), curve, trades, metrics, runner.cfg.model_dump(mode="json"))
    out = Path(runner.reports_dir) / runner.run_id / f"live-{runner.clock.now():%Y%m%d}.html"
    return render_report(result, out, display_tz=runner.cfg.display_tz)
