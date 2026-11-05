"""Configuration models: YAML run configs and environment-sourced secrets.

A run config is parsed from YAML into :class:`RunConfig`, validated, and can be printed back with
defaults filled so the owner can see exactly what a run will do. Secrets come only from the
environment through :class:`Secrets`, are held as ``SecretStr``, and are never serialised.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from kestrel.errors import ConfigError

Market = Literal["crypto", "equities"]
Timeframe = Literal["1m", "5m", "15m", "1h", "4h", "1d"]

TIMEFRAME_SECONDS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3_600,
    "4h": 14_400,
    "1d": 86_400,
}


class _Strict(BaseModel):
    """Base for config sections: unknown keys are errors, assignment is validated."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class AdapterConfig(_Strict):
    """Which execution adapter a paper run uses. There is no live option by design."""

    kind: Literal["mock", "ccxt", "alpaca"] = "mock"
    exchange: str = "binance"
    """CCXT exchange id. Must have a sandbox; checked at adapter construction."""
    mock_scenario: Path | None = None
    """Optional YAML scenario file for the mock adapter."""


class DataConfig(_Strict):
    """Data layer settings."""

    source: Literal["ccxt", "alpaca", "yfinance", "fixtures", "synthetic"] = "ccxt"
    exchange: str = "binance"
    cache_dir: Path = Path("data/cache")
    manifest_path: Path = Path("data/manifest.json")
    fixtures_dir: Path | None = None
    allow_gaps: bool = False
    max_partition_mb: int = 50
    rate_limit_per_second: float = 5.0


class StrategyConfig(_Strict):
    """Strategy selection and its parameters (validated by the strategy's own model)."""

    name: str
    params: dict[str, Any] = Field(default_factory=dict)


class FeeConfig(_Strict):
    """Fee model. Crypto taker 10 bps; equities zero commission plus a 2 bps half-spread."""

    rate_bps: float = 10.0


class SlippageConfig(_Strict):
    """Slippage model: ``base_bps + impact_k * participation`` capped at ``cap_bps``."""

    base_bps: float = 5.0
    impact_k: float = 0.1
    cap_bps: float = 50.0


class BacktestConfig(_Strict):
    """Backtest window and execution assumptions."""

    start: date
    end: date
    initial_cash: float = 100_000.0
    fill_at: Literal["next_open", "this_close"] = "next_open"
    max_participation: float = 0.05
    fees: FeeConfig = Field(default_factory=FeeConfig)
    slippage: SlippageConfig = Field(default_factory=SlippageConfig)
    seed: int = 42

    @model_validator(mode="after")
    def _check_dates(self) -> BacktestConfig:
        if self.end <= self.start:
            raise ValueError(f"backtest.end ({self.end}) must be after backtest.start ({self.start})")
        return self

    @property
    def start_ts(self) -> datetime:
        """Start of the window as a UTC datetime."""
        return datetime(self.start.year, self.start.month, self.start.day, tzinfo=UTC)

    @property
    def end_ts(self) -> datetime:
        """End of the window (inclusive date, exclusive instant at midnight after) as UTC."""
        return datetime(self.end.year, self.end.month, self.end.day, 23, 59, 59, tzinfo=UTC)


class RiskConfig(_Strict):
    """Position sizing and hard limits. Enforced before any order exists."""

    sizing: Literal["fixed_fraction", "vol_target"] = "fixed_fraction"
    target_vol: float = 0.15
    vol_lookback: int = 20
    max_weight_per_symbol: float = 0.25
    max_gross_exposure: float = 1.0
    max_orders_per_bar: int = 20
    max_daily_loss: float = 0.03
    max_drawdown: float = 0.15
    max_consecutive_adapter_errors: int = 5
    stale_data_bars: int = 2
    stale_notify_after: int = 3

    @field_validator("max_weight_per_symbol", "max_gross_exposure", "max_daily_loss", "max_drawdown")
    @classmethod
    def _unit_interval(cls, v: float) -> float:
        if not 0 < v <= 1.0:
            raise ValueError("must be in (0, 1]")
        return v


class ValidationConfig(_Strict):
    """Thresholds for the validation verdict."""

    n_windows: int = 6
    walk_forward_mode: Literal["rolling", "anchored"] = "rolling"
    n_trials: int | None = None
    """Number of strategy variants tried; defaults to the sweep grid size or 1."""
    dsr_fail: float = 0.90
    dsr_caution: float = 0.95
    oos_is_ratio_fail: float = 0.3
    oos_is_ratio_caution: float = 0.5
    min_trades: int = 30
    sensitivity_drop: float = 0.5
    sensitivity_step: float = 0.2
    mc_resamples: int = 1000
    bootstrap_resamples: int = 1000
    bootstrap_block: int = 20
    max_plausible_sharpe: float = 5.0
    max_plausible_hit_rate: float = 0.90
    memorisation_resamples: int = 5
    memorisation_retention: float = 0.25
    """Fraction of the original Sharpe a strategy must keep on resampled data."""
    ruin_probability_caution: float = 0.05


class LiveConfig(_Strict):
    """Scheduling and timeouts for the paper loop."""

    state_dir: Path = Path("state")
    order_timeout_s: int = 60
    poll_interval_s: float = 2.0
    drift_notify_fraction: float = 0.01
    daily_report_time: str = "08:00"
    weekly_report_day: Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"] = "mon"
    cycle_offset_s: int = 5
    """Seconds after the bar close to start a cycle, so the bar is published."""


class NotifyConfig(_Strict):
    """Notifier selection; the Telegram token itself comes from the environment."""

    kind: Literal["auto", "telegram", "console", "null"] = "auto"
    rate_limit_minutes: int = 15


class LLMConfig(_Strict):
    """Optional AI narrative. Off unless enabled and a key is present."""

    enabled: bool = False
    provider: Literal["auto", "anthropic", "openai"] = "auto"
    model: str | None = None
    monthly_token_budget: int = 200_000
    max_output_tokens: int = 800


class NewsConfig(_Strict):
    """Optional news headlines on the daily report."""

    enabled: bool = False
    max_headlines: int = 5


class IntegrationsConfig(_Strict):
    """All optional integrations. The bot runs fully without any of them."""

    llm: LLMConfig = Field(default_factory=LLMConfig)
    news: NewsConfig = Field(default_factory=NewsConfig)


class RunConfig(_Strict):
    """One complete run configuration for a backtest, a validation, or a paper loop."""

    market: Market = "crypto"
    timeframe: Timeframe = "1d"
    adapter: AdapterConfig = Field(default_factory=AdapterConfig)
    data: DataConfig = Field(default_factory=DataConfig)
    universe: str = "crypto_top20"
    universe_dir: Path = Path("configs/universes")
    strategy: StrategyConfig
    risk: RiskConfig = Field(default_factory=RiskConfig)
    backtest: BacktestConfig
    validation: ValidationConfig = Field(default_factory=ValidationConfig)
    live: LiveConfig = Field(default_factory=LiveConfig)
    notify: NotifyConfig = Field(default_factory=NotifyConfig)
    integrations: IntegrationsConfig = Field(default_factory=IntegrationsConfig)
    display_tz: str = "Asia/Bangkok"
    reports_dir: Path = Path("reports")
    artifacts_dir: Path = Path("artifacts")

    @field_validator("display_tz")
    @classmethod
    def _valid_tz(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown time zone {v!r}") from exc
        return v

    @model_validator(mode="after")
    def _market_defaults(self) -> RunConfig:
        if self.market == "equities" and "fees" not in self.backtest.model_fields_set:
            self.backtest.fees = FeeConfig(rate_bps=2.0)
        return self

    @property
    def bar_seconds(self) -> int:
        """Length of one bar in seconds."""
        return TIMEFRAME_SECONDS[self.timeframe]

    @property
    def annualisation(self) -> float:
        """Bars per year for Sharpe annualisation, by market and timeframe."""
        return annualisation_factor(self.market, self.timeframe)

    def to_yaml(self) -> str:
        """Serialise with every default filled in, for ``kestrel`` to print before a run."""
        data = self.model_dump(mode="json")
        return yaml.safe_dump(data, sort_keys=False, default_flow_style=False)


def annualisation_factor(market: str, timeframe: str) -> float:
    """Bars per year used to annualise returns and volatility.

    Args:
        market: ``crypto`` (24/7) or ``equities`` (NYSE hours).
        timeframe: Bar size, e.g. ``1d`` or ``1h``.

    Returns:
        365 for crypto daily, 252 for equities daily, 8 760 for crypto hourly, 1 638 for equities
        hourly, and proportional values for other intraday bars.
    """
    seconds = TIMEFRAME_SECONDS[timeframe]
    if market == "crypto":
        return 365.0 * 86_400 / seconds
    if timeframe == "1d":
        return 252.0
    return 252.0 * 6.5 * 3_600 / seconds


def load_run_config(path: Path | str) -> RunConfig:
    """Load and validate a run config from YAML.

    Args:
        path: Path to a YAML file.

    Returns:
        The validated :class:`RunConfig`.

    Raises:
        ConfigError: If the file is missing, is not a mapping, or fails validation. The message
            names the offending field.
    """
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"config file not found: {p}")
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"could not parse YAML in {p}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"config {p} must be a mapping at the top level")
    return parse_run_config(raw, source=str(p))


def parse_run_config(raw: dict[str, Any], source: str = "<dict>") -> RunConfig:
    """Validate a raw mapping into a :class:`RunConfig`, re-raising as :class:`ConfigError`."""
    try:
        return RunConfig.model_validate(raw)
    except ValueError as exc:
        raise ConfigError(f"invalid config ({source}):\n{_format_pydantic(exc)}") from exc


def _format_pydantic(exc: ValueError) -> str:
    errors = getattr(exc, "errors", None)
    if errors is None:
        return str(exc)
    lines = []
    for err in errors():
        loc = ".".join(str(part) for part in err.get("loc", ())) or "<root>"
        lines.append(f"  {loc}: {err.get('msg')}")
    return "\n".join(lines) or str(exc)


class Secrets(BaseSettings):
    """Secrets read once from the environment. Never serialised, never logged.

    ``repr`` and ``str`` of a ``SecretStr`` print ``**********``; ``kestrel doctor`` reports
    presence only.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    apca_api_key_id: SecretStr | None = Field(default=None, alias="APCA_API_KEY_ID")
    apca_api_secret_key: SecretStr | None = Field(default=None, alias="APCA_API_SECRET_KEY")
    kestrel_ccxt_exchange: str = Field(default="binance", alias="KESTREL_CCXT_EXCHANGE")
    kestrel_ccxt_api_key: SecretStr | None = Field(default=None, alias="KESTREL_CCXT_API_KEY")
    kestrel_ccxt_secret: SecretStr | None = Field(default=None, alias="KESTREL_CCXT_SECRET")
    kestrel_telegram_token: SecretStr | None = Field(default=None, alias="KESTREL_TELEGRAM_TOKEN")
    kestrel_telegram_chat_id: str | None = Field(default=None, alias="KESTREL_TELEGRAM_CHAT_ID")
    anthropic_api_key: SecretStr | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    openai_api_key: SecretStr | None = Field(default=None, alias="OPENAI_API_KEY")
    kestrel_news_api_key: SecretStr | None = Field(default=None, alias="KESTREL_NEWS_API_KEY")
    kestrel_display_tz: str = Field(default="Asia/Bangkok", alias="KESTREL_DISPLAY_TZ")
    kestrel_integration: str | None = Field(default=None, alias="KESTREL_INTEGRATION")

    @field_validator(
        "apca_api_key_id",
        "apca_api_secret_key",
        "kestrel_ccxt_api_key",
        "kestrel_ccxt_secret",
        "kestrel_telegram_token",
        "anthropic_api_key",
        "openai_api_key",
        "kestrel_news_api_key",
        mode="before",
    )
    @classmethod
    def _blank_is_none(cls, v: object) -> object:
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    def has(self, name: str) -> bool:
        """Return whether the named secret is present and non-empty, without revealing it."""
        value = getattr(self, name, None)
        if value is None:
            return False
        if isinstance(value, SecretStr):
            return bool(value.get_secret_value())
        return bool(value)

    def presence(self) -> dict[str, bool]:
        """Map of every secret field to whether it is set. Safe to print."""
        return {
            name: self.has(name)
            for name, field in type(self).model_fields.items()
            if field.annotation is not None and "SecretStr" in str(field.annotation)
        }

    def __repr__(self) -> str:
        """Never expose values."""
        return f"Secrets({self.presence()})"

    __str__ = __repr__

    @property
    def integration_tests_enabled(self) -> bool:
        """True when ``KESTREL_INTEGRATION=1``."""
        return self.kestrel_integration == "1"
