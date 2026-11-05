"""JSON export of a backtest result with stable keys and a schema version."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from kestrel.backtest.engine import BacktestResult

SCHEMA_VERSION = 1


def _default(obj: object) -> object:
    if isinstance(obj, np.floating | np.integer):
        return obj.item()
    if isinstance(obj, float) and (obj != obj or obj in (float("inf"), float("-inf"))):
        return None
    return str(obj)


def metrics_payload(result: BacktestResult, validation: dict[str, Any] | None = None) -> dict[str, Any]:
    """The ``metrics.json`` document."""
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": result.run_id,
        "strategy": result.strategy,
        "params": result.params,
        "metrics": result.metrics,
        "validation": validation,
        "config": result.config,
        "n_events": len(result.events),
    }


def write_metrics_json(result: BacktestResult, path: Path, validation: dict[str, Any] | None = None) -> Path:
    """Write ``metrics.json`` deterministically (sorted keys)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metrics_payload(result, validation), indent=2, sort_keys=True, default=_default), encoding="utf-8")
    return path
