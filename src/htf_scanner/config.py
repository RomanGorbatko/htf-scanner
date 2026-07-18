import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ScannerConfig(StrictModel):
    version: str = "0.1.0"
    timezone: Literal["UTC"] = "UTC"
    confirmed_candles_only: bool = True


class AtrConfig(StrictModel):
    period: int = Field(default=14, ge=1)


class FvgConfig(StrictModel):
    minimum_size_atr: float = Field(default=0.08, ge=0)
    maximum_size_atr: float = Field(default=5.0, gt=0)
    expire_after_d1_bars: int = Field(default=90, ge=1)
    invalidation_mode: Literal["close_through_far_edge"] = "close_through_far_edge"


class SwingConfig(StrictModel):
    reversal_atr: float = Field(default=1.0, gt=0)
    minimum_bars_between_swings: int = Field(default=2, ge=1)
    use_close_for_confirmation: bool = False


class StructureConfig(StrictModel):
    break_mode: Literal["close", "close_plus_buffer"] = "close_plus_buffer"
    minimum_break_atr: float = Field(default=0.05, ge=0)


class LiquidityConfig(StrictModel):
    minimum_sweep_atr: float = Field(default=0.02, ge=0)
    maximum_sweep_atr: float = Field(default=1.5, gt=0)
    max_acceptance_closes: int = Field(default=1, ge=0)
    return_window_bars: int = Field(default=3, ge=1)
    failed_continuation_max_distance_atr: float = Field(default=0.5, ge=0)
    failed_continuation_followup_bars: int = Field(default=5, ge=1)
    minimum_retracement_atr: float = Field(default=0.5, ge=0)
    accepted_breakout_min_closes: int = Field(default=2, ge=1)
    accepted_breakout_min_atr: float = Field(default=0.15, ge=0)
    distance_penalty_max: float = Field(default=1.0, ge=0)
    timing_penalty_max: float = Field(default=1.0, ge=0)


class DisplacementConfig(StrictModel):
    minimum_score: float = Field(default=3.0, ge=0)
    minimum_body_atr: float = Field(default=0.8, ge=0)
    minimum_range_atr: float = Field(default=1.2, ge=0)
    minimum_net_move_atr: float = Field(default=0.8, ge=0)
    minimum_body_efficiency: float = Field(default=0.6, ge=0, le=1)
    bearish_max_close_location: float = Field(default=0.30, ge=0, le=1)
    bullish_min_close_location: float = Field(default=0.70, ge=0, le=1)
    maximum_sequence_bars: int = Field(default=3, ge=1, le=10)


class D1SetupConfig(StrictModel):
    minimum_displacement_score: float = Field(default=3.0, ge=0)
    minimum_context_score: float = Field(default=1.0, ge=0)
    minimum_quality_score: float = Field(default=5.0, ge=0)
    require_structure_break: bool = True
    structure_break_max_lag_bars: int = Field(default=1, ge=0)
    max_setup_age_bars: int = Field(default=90, ge=1)


class H4TouchConfig(StrictModel):
    phase_gap_bars: int = Field(default=1, ge=0)
    midpoint_fraction: float = Field(default=0.5, gt=0, lt=1)
    full_fill_fraction: float = Field(default=1.0, gt=0, le=1)


class H4ReactionConfig(StrictModel):
    minimum_early_score: float = Field(default=1.0, ge=0)
    rejection_wick_body_ratio: float = Field(default=0.5, ge=0)
    maximum_bars_activation_to_touch: int = Field(default=90, ge=1)
    maximum_bars_touch_to_confirmation: int = Field(default=18, ge=1)
    maximum_total_bars: int = Field(default=120, ge=1)
    require_h4_fvg: bool = False
    touch_quality_weight: float = Field(default=1.0, ge=0)
    close_back_weight: float = Field(default=1.5, ge=0)
    rejection_candle_weight: float = Field(default=1.0, ge=0)
    lower_close_weight: float = Field(default=0.75, ge=0)
    local_liquidity_weight: float = Field(default=0.5, ge=0)
    displacement_weight: float = Field(default=1.5, ge=0)
    fvg_weight: float = Field(default=1.0, ge=0)
    freshness_weight: float = Field(default=0.75, ge=0)
    depth_penalty_weight: float = Field(default=1.0, ge=0)
    dwell_penalty_per_bar: float = Field(default=0.1, ge=0)


class H4InvalidationConfig(StrictModel):
    boundary_buffer_atr: float = Field(default=0.05, ge=0)
    minimum_closes_beyond: int = Field(default=2, ge=1)
    hold_bars: int = Field(default=2, ge=1)
    reclaim_window_bars: int = Field(default=1, ge=0)
    maximum_excursion_atr: float = Field(default=1.5, gt=0)


class ReactionOutcomesConfig(StrictModel):
    horizons: list[int] = Field(default_factory=lambda: [6, 12, 24, 42], min_length=1)
    fixed_atr_targets: list[float] = Field(default_factory=lambda: [1.0, 2.0, 3.0])
    continuation_atr: float = Field(default=1.0, gt=0)
    failure_atr: float = Field(default=1.0, gt=0)


class BatchScanConfig(StrictModel):
    minimum_d1_candles: int = Field(default=60, ge=3)
    minimum_h4_candles: int = Field(default=100, ge=3)
    continue_on_symbol_error: bool = True


class StorageConfig(StrictModel):
    database_url: str = "sqlite:///data/htf_scanner.db"
    candle_cache_dir: Path = Path("data/candles")


class ReportsConfig(StrictModel):
    output_dir: Path = Path("reports")
    chart_format: Literal["png"] = "png"


class MarketDataConfig(StrictModel):
    provider: str = Field(default="binance", min_length=1)
    base_url: str = "https://fapi.binance.com"
    timeout_seconds: float = Field(default=30.0, gt=0)


class ExchangeConfig(StrictModel):
    quote_asset: str = "USDT"
    contract_type: Literal["PERPETUAL"] = "PERPETUAL"


class UniverseConfig(StrictModel):
    active_only: bool = True
    minimum_history_days: int = Field(default=180, ge=0)
    minimum_quote_volume_24h: float = Field(default=0.0, ge=0)
    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    maximum_symbols: int | None = Field(default=None, ge=1)


class TelegramConfig(StrictModel):
    enabled: bool = False
    bot_token_env: str = "HTF_TELEGRAM_BOT_TOKEN"
    chat_id_env: str = "HTF_TELEGRAM_CHAT_ID"
    api_base_url: str = "https://api.telegram.org"
    timeout_seconds: float = Field(default=15.0, gt=0)
    parse_mode: Literal["MarkdownV2"] = "MarkdownV2"


def telegram_environment_names_valid(config: TelegramConfig) -> bool:
    pattern = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
    return bool(pattern.fullmatch(config.bot_token_env)) and bool(
        pattern.fullmatch(config.chat_id_env)
    )


class AlertsConfig(StrictModel):
    enabled: bool = True
    bootstrap_policy: Literal["suppress"] = "suppress"
    event_types: list[str] = Field(
        default_factory=lambda: [
            "D1_SETUP_ACTIVE",
            "H4_REACTION_CONFIRMED",
        ]
    )
    attach_chart: bool = False
    maximum_delivery_attempts: int = Field(default=12, ge=1)
    retry_failed_after_minutes: int = Field(default=60, ge=1)


class RetryConfig(StrictModel):
    attempts: int = Field(default=4, ge=1)
    initial_backoff_seconds: float = Field(default=0.5, ge=0)
    maximum_backoff_seconds: float = Field(default=8.0, ge=0)


class SchedulerConfig(StrictModel):
    lock_path: Path = Path("data/scan-live-once.lock")
    expected_interval_minutes: int = Field(default=60, ge=1)
    stale_after_minutes: int = Field(default=180, ge=1)


class RuntimeConfig(StrictModel):
    bootstrap_start: datetime = datetime(2024, 1, 1)
    state_dir: Path = Path("data/state")
    report_dir: Path = Path("reports/live")
    rebuild_on_config_change: bool = True
    continue_on_symbol_error: bool = True


class AppConfig(StrictModel):
    scanner: ScannerConfig = ScannerConfig()
    atr: AtrConfig = AtrConfig()
    swings: SwingConfig = SwingConfig()
    structure: StructureConfig = StructureConfig()
    liquidity: LiquidityConfig = LiquidityConfig()
    fvg: FvgConfig = FvgConfig()
    displacement: DisplacementConfig = DisplacementConfig()
    d1_setup: D1SetupConfig = D1SetupConfig()
    h4_swing: SwingConfig = SwingConfig(reversal_atr=0.75, minimum_bars_between_swings=1)
    h4_structure: StructureConfig = StructureConfig()
    h4_displacement: DisplacementConfig = DisplacementConfig()
    h4_touch: H4TouchConfig = H4TouchConfig()
    h4_reaction: H4ReactionConfig = H4ReactionConfig()
    h4_invalidation: H4InvalidationConfig = H4InvalidationConfig()
    reaction_outcomes: ReactionOutcomesConfig = ReactionOutcomesConfig()
    batch_scan: BatchScanConfig = BatchScanConfig()
    storage: StorageConfig = StorageConfig()
    reports: ReportsConfig = ReportsConfig()
    market_data: MarketDataConfig = MarketDataConfig()
    exchange: ExchangeConfig = ExchangeConfig()
    universe: UniverseConfig = UniverseConfig()
    telegram: TelegramConfig = TelegramConfig()
    alerts: AlertsConfig = AlertsConfig()
    retry: RetryConfig = RetryConfig()
    scheduler: SchedulerConfig = SchedulerConfig()
    runtime: RuntimeConfig = RuntimeConfig()


def load_config(path: Path | None = None) -> AppConfig:
    if path is None:
        default_path = Path("config.yaml")
        path = default_path if default_path.exists() else None
    if path is None:
        return AppConfig()
    with path.open(encoding="utf-8") as config_file:
        raw = yaml.safe_load(config_file) or {}
    return AppConfig.model_validate(raw)


def configuration_hash(config: AppConfig) -> str:
    canonical = json.dumps(
        config.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
