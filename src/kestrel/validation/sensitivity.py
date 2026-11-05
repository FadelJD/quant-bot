"""Parameter sensitivity: a real edge is a plateau, an overfit one is a spike."""

from __future__ import annotations

import itertools
from collections.abc import Callable
from typing import Any


def neighbour_grid(params: dict[str, Any], step: float = 0.2, max_params: int = 3) -> list[dict[str, Any]]:
    """Return the grid of ``params`` perturbed by ``+-step`` on each numeric field (3^k points).

    Integer params stay integers and never collapse onto the centre; non-numeric and boolean
    fields are left untouched. At most ``max_params`` numeric fields are varied.
    """
    numeric = [k for k, v in params.items() if isinstance(v, int | float) and not isinstance(v, bool)][:max_params]
    if not numeric:
        return [dict(params)]
    axes: list[list[Any]] = []
    for k in numeric:
        v = params[k]
        if isinstance(v, int):
            delta = max(1, round(abs(v) * step))
            axes.append([v - delta, v, v + delta])
        else:
            axes.append([v * (1 - step), v, v * (1 + step)])
    grid = []
    for combo in itertools.product(*axes):
        p = dict(params)
        for k, val in zip(numeric, combo, strict=True):
            p[k] = val
        grid.append(p)
    return grid


def parameter_sensitivity(
    evaluate: Callable[[dict[str, Any]], float | None],
    params: dict[str, Any],
    *,
    step: float = 0.2,
    drop_threshold: float = 0.5,
) -> dict[str, Any]:
    """Evaluate the neighbour grid and flag a sharp peak.

    Args:
        evaluate: ``params -> Sharpe`` (``None`` for an invalid combination).
        params: The chosen parameters (centre of the grid).
        step: Relative perturbation.
        drop_threshold: Flag if any valid neighbour's Sharpe is below ``(1 - drop) * centre``.

    Returns:
        ``{"centre": .., "points": [...], "min_neighbour": .., "sharp_peak": bool, "axes": [...]}``.
    """
    grid = neighbour_grid(params, step)
    points = []
    centre_sharpe: float | None = None
    for p in grid:
        s = evaluate(p)
        points.append({"params": p, "sharpe": s})
        if p == params:
            centre_sharpe = s
    if centre_sharpe is None:
        centre_sharpe = evaluate(params)
    valid = [pt["sharpe"] for pt in points if pt["sharpe"] is not None and pt["params"] != params]
    min_nb = min(valid) if valid else None
    sharp = bool(centre_sharpe is not None and centre_sharpe > 0 and min_nb is not None and min_nb < (1 - drop_threshold) * centre_sharpe)
    numeric = [k for k, v in params.items() if isinstance(v, int | float) and not isinstance(v, bool)][:2]
    return {
        "centre": centre_sharpe,
        "points": points,
        "min_neighbour": min_nb,
        "sharp_peak": sharp,
        "axes": numeric,
    }
