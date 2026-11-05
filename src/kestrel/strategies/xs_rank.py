"""``xs_rank``: LightGBM cross-sectional ranker, retrained on a fixed cadence with an embargo.

Requires the ``[ml]`` extra. Importing this module never imports LightGBM; construction does.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
import pandas as pd
from pydantic import Field

from kestrel.errors import ConfigError
from kestrel.strategies.base import BarContext, Strategy, StrategyParams, register_strategy


class XsRankParams(StrategyParams):
    """Parameters for :class:`XsRank`."""

    horizon: int = Field(default=20, ge=1, le=120, description="Label horizon in bars (also the embargo)")
    retrain_every: int = Field(default=60, ge=5, description="Retrain cadence in bars")
    rebalance_every: int = Field(default=5, ge=1, description="Rebalance cadence in bars (5 = weekly on daily bars)")
    top_k: int = Field(default=5, ge=1, description="Hold the top-k predicted names")
    min_train_bars: int = Field(default=250, ge=50, description="Bars of history before the first model")
    n_estimators: int = Field(default=200, ge=10, le=2000)
    learning_rate: float = Field(default=0.05, gt=0, le=1)
    num_leaves: int = Field(default=15, ge=2, le=255)
    seed: int = 42
    model_dir: str = "artifacts/models"


FEATURE_COLS: tuple[str, ...] = (
    "ret_5",
    "ret_20",
    "ret_60",
    "vol_20",
    "vol_60",
    "volz_20",
    "xs_rank_ret_20",
    "xs_rank_vol_20",
    "xs_z_ret_60",
)


@register_strategy
class XsRank(Strategy):
    """Predict the next-``horizon`` return rank; hold the top-k equal weight."""

    name = "xs_rank"
    Params = XsRankParams
    description = (
        "LightGBM regressor predicts the cross-sectional rank of the next-horizon return from momentum, "
        "volatility and volume features; holds top-k equal weight, rebalances on a fixed cadence."
    )
    cross_sectional = ("ret_20", "vol_20", "ret_60")
    params: XsRankParams

    def __init__(self, params: XsRankParams, *, timeframe: str = "1d", universe: str = "") -> None:
        """Create the strategy and verify LightGBM is importable."""
        super().__init__(params, timeframe=timeframe, universe=universe)
        try:
            import lightgbm  # noqa: F401
        except ImportError as exc:  # pragma: no cover - depends on the environment
            raise ConfigError("strategy xs_rank needs the ml extra: pip install 'kestrel[ml]'") from exc
        self._model: Any | None = None
        self._last_train_bar = -10**9
        self._last_rebalance_bar = -10**9
        self._current: dict[str, float] = {}
        self._fold = 0
        self.train_count = 0

    @property
    def requires(self) -> list[str]:
        """Momentum, volatility and volume features."""
        return ["ret_5", "ret_20", "ret_60", "vol_20", "vol_60", "volz_20"]

    def warmup_bars(self) -> int:
        """Enough history for the first model."""
        return self.params.min_train_bars

    # ------------------------------------------------------------------ training

    def _training_set(self, ctx: BarContext) -> tuple[np.ndarray, np.ndarray]:
        """Build (X, y) strictly before ``ctx.ts`` with an embargo of ``horizon`` bars.

        A sample at bar ``i`` has label ``close[i+h]/close[i]-1``; it is used only if
        ``i + h < n - 1 - h`` where ``n - 1`` is the current bar, i.e. the label window ends at
        least ``horizon`` bars before the prediction bar. Labels are then cross-sectionally
        ranked per timestamp.
        """
        h = self.params.horizon
        rows: list[pd.DataFrame] = []
        for sym, frame in ctx.features.items():
            n = len(frame)
            cutoff = n - 1 - h  # last bar whose label does not overlap the embargo
            usable = frame.iloc[: cutoff - h + 1] if cutoff - h + 1 > 0 else frame.iloc[:0]
            if usable.empty:
                continue
            fut = frame["close"].shift(-h) / frame["close"] - 1.0
            sub = usable[list(FEATURE_COLS)].copy()
            sub["y"] = fut.iloc[: len(usable)].to_numpy()
            sub["sym"] = sym
            rows.append(sub)
        if not rows:
            return np.empty((0, len(FEATURE_COLS))), np.empty(0)
        data = pd.concat(rows).dropna()
        if data.empty:
            return np.empty((0, len(FEATURE_COLS))), np.empty(0)
        data["y_rank"] = data.groupby(level=0)["y"].rank(pct=True)
        return data[list(FEATURE_COLS)].to_numpy(dtype=float), data["y_rank"].to_numpy(dtype=float)

    def _train(self, ctx: BarContext) -> None:
        import lightgbm as lgb

        x, y = self._training_set(ctx)
        if len(y) < 50:
            return
        model = lgb.LGBMRegressor(
            n_estimators=self.params.n_estimators,
            learning_rate=self.params.learning_rate,
            num_leaves=self.params.num_leaves,
            random_state=self.params.seed,
            verbose=-1,
            n_jobs=1,
            deterministic=True,
            force_col_wise=True,
        )
        model.fit(x, y)
        self._model = model
        self.train_count += 1
        self._fold += 1
        self._persist(ctx)

    def _persist(self, ctx: BarContext) -> None:
        if self._model is None:
            return
        out = Path(self.params.model_dir)
        try:
            out.mkdir(parents=True, exist_ok=True)
            stamp = ctx.ts.strftime("%Y%m%dT%H%M%SZ")
            self._model.booster_.save_model(str(out / f"xs_rank_fold{self._fold:03d}_{stamp}.txt"))
            (out / "latest.json").write_text(
                json.dumps({"fold": self._fold, "trained_at": ctx.ts.isoformat()}), encoding="utf-8"
            )
        except OSError:  # pragma: no cover - persistence is best effort
            pass

    # ------------------------------------------------------------------ decisions

    def on_bar(self, ctx: BarContext) -> dict[str, float]:
        """Retrain on cadence, rebalance on cadence, otherwise hold the current book."""
        i = ctx.bar_index
        if self._model is None or i - self._last_train_bar >= self.params.retrain_every:
            self._train(ctx)
            self._last_train_bar = i
        if self._model is None:
            return {}
        if i - self._last_rebalance_bar < self.params.rebalance_every and self._current:
            return dict(self._current)
        scores: dict[str, float] = {}
        for sym, frame in ctx.features.items():
            row = frame.iloc[-1]
            vals = row[list(FEATURE_COLS)].to_numpy(dtype=float)
            if np.isnan(vals).any():
                continue
            scores[sym] = float(self._model.predict(vals.reshape(1, -1))[0])
        top = sorted(scores, key=lambda s: (-scores[s], s))[: self.params.top_k]
        self._current = dict.fromkeys(top, 1.0 / len(top)) if top else {}
        self._last_rebalance_bar = i
        return dict(self._current)

    def state(self) -> dict[str, Any]:
        """Cadence counters and the current book (model files live under ``model_dir``)."""
        return {
            "last_train_bar": self._last_train_bar,
            "last_rebalance_bar": self._last_rebalance_bar,
            "current": dict(self._current),
            "fold": self._fold,
        }

    def load_state(self, s: dict[str, Any]) -> None:
        """Restore counters; the model is retrained on the next bar if missing."""
        self._last_train_bar = int(s.get("last_train_bar", -10**9))
        self._last_rebalance_bar = int(s.get("last_rebalance_bar", -10**9))
        self._current = {str(k): float(v) for k, v in dict(s.get("current", {})).items()}
        self._fold = int(s.get("fold", 0))
