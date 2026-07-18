from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


class DecimalText(TypeDecorator[Decimal]):
    """Persist exact exchange decimals as text instead of SQLite floating point."""

    impl = String(64)
    cache_ok = True

    def process_bind_param(self, value: Decimal | None, dialect: Dialect) -> str | None:
        return None if value is None else str(value)

    def process_result_value(self, value: Any, dialect: Dialect) -> Decimal | None:
        return None if value is None else Decimal(str(value))


class Base(DeclarativeBase):
    pass


class CandleRow(Base):
    __tablename__ = "candles"
    __table_args__ = (
        Index("ux_candles_market_time", "symbol", "timeframe", "open_time", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    close_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[Decimal] = mapped_column(DecimalText(), nullable=False)
    high: Mapped[Decimal] = mapped_column(DecimalText(), nullable=False)
    low: Mapped[Decimal] = mapped_column(DecimalText(), nullable=False)
    close: Mapped[Decimal] = mapped_column(DecimalText(), nullable=False)
    volume: Mapped[Decimal] = mapped_column(DecimalText(), nullable=False)
    quote_volume: Mapped[Decimal | None] = mapped_column(DecimalText())
    trades: Mapped[int | None] = mapped_column(Integer)
    is_closed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class FvgRow(Base):
    __tablename__ = "fvgs"
    __table_args__ = (Index("ix_fvgs_market_known", "symbol", "timeframe", "known_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    formed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class SwingRow(Base):
    __tablename__ = "swings"
    __table_args__ = (Index("ix_swings_market_known", "symbol", "timeframe", "known_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    formed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class StructureBreakRow(Base):
    __tablename__ = "structure_breaks"
    __table_args__ = (Index("ix_structure_breaks_market_known", "symbol", "timeframe", "known_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    formed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class StructurePromotionRow(Base):
    __tablename__ = "structure_promotions"
    __table_args__ = (
        Index("ix_structure_promotions_market_time", "symbol", "timeframe", "promoted_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    promoted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class DisplacementRow(Base):
    __tablename__ = "displacements"
    __table_args__ = (Index("ix_displacements_market_known", "symbol", "timeframe", "known_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    formed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class LiquidityContextRow(Base):
    __tablename__ = "liquidity_contexts"
    __table_args__ = (
        Index("ix_liquidity_contexts_market_known", "symbol", "timeframe", "known_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    formed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class LiquidityInteractionRow(Base):
    __tablename__ = "liquidity_interactions"
    __table_args__ = (
        Index(
            "ix_liquidity_interactions_level_known",
            "external_level_id",
            "known_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    external_level_id: Mapped[str] = mapped_column(String(36), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    formed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class LiquiditySequenceRow(Base):
    __tablename__ = "liquidity_sequences"
    __table_args__ = (
        Index("ix_liquidity_sequences_market_known", "symbol", "timeframe", "known_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    formed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class HTFSetupRow(Base):
    __tablename__ = "htf_setups"
    __table_args__ = (Index("ix_htf_setups_market_known", "symbol", "timeframe", "known_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    formed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fvg_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class HTFSetupTransitionRow(Base):
    __tablename__ = "htf_setup_transitions"
    __table_args__ = (Index("ix_setup_transitions_setup_known", "setup_id", "known_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    setup_id: Mapped[str] = mapped_column(String(36), nullable=False)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class RejectedSetupCandidateRow(Base):
    __tablename__ = "rejected_setup_candidates"
    __table_args__ = (
        Index("ix_rejected_candidates_market_time", "symbol", "timeframe", "rejected_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    rejected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class D1SetupCandidateRow(Base):
    __tablename__ = "d1_setup_candidates"
    __table_args__ = (
        Index("ix_d1_setup_candidates_market_known", "symbol", "timeframe", "known_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class MergedSetupCandidateRow(Base):
    __tablename__ = "merged_setup_candidates"
    __table_args__ = (
        Index("ix_merged_candidates_market_known", "symbol", "timeframe", "known_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class H4ReactionRow(Base):
    __tablename__ = "h4_reactions"
    __table_args__ = (Index("ix_h4_reactions_setup_known", "setup_id", "known_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    setup_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class SetupOutcomeRow(Base):
    __tablename__ = "setup_outcomes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    setup_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class H4TouchPhaseRow(Base):
    __tablename__ = "h4_touch_phases"
    __table_args__ = (Index("ix_h4_touch_phases_setup_known", "setup_id", "known_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    setup_id: Mapped[str] = mapped_column(ForeignKey("htf_setups.id"), nullable=False)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class H4ReactionCandidateRow(Base):
    __tablename__ = "h4_reaction_candidates"
    __table_args__ = (Index("ix_h4_candidates_setup_known", "setup_id", "known_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    setup_id: Mapped[str] = mapped_column(ForeignKey("htf_setups.id"), nullable=False)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class H4MergedCandidateRow(Base):
    __tablename__ = "h4_merged_candidates"
    __table_args__ = (Index("ix_h4_merged_setup_known", "setup_id", "known_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    setup_id: Mapped[str] = mapped_column(ForeignKey("htf_setups.id"), nullable=False)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class H4ReactionTransitionRow(Base):
    __tablename__ = "h4_reaction_transitions"
    __table_args__ = (Index("ix_h4_transitions_reaction_known", "reaction_id", "known_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    reaction_id: Mapped[str] = mapped_column(ForeignKey("h4_reactions.id"), nullable=False)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ReactionOutcomeRow(Base):
    __tablename__ = "reaction_outcomes"
    __table_args__ = (
        Index("ix_reaction_outcomes_reaction_horizon", "reaction_id", "horizon_bars"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    reaction_id: Mapped[str] = mapped_column(ForeignKey("h4_reactions.id"), nullable=False)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    horizon_bars: Mapped[int] = mapped_column(Integer, nullable=False)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ReactionTargetOutcomeRow(Base):
    __tablename__ = "reaction_target_outcomes"
    __table_args__ = (Index("ix_reaction_targets_reaction_known", "reaction_id", "known_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    reaction_id: Mapped[str] = mapped_column(ForeignKey("h4_reactions.id"), nullable=False)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class BatchRunRow(Base):
    __tablename__ = "batch_runs"
    __table_args__ = (Index("ix_batch_runs_config_started", "config_hash", "started_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class BatchSymbolRunRow(Base):
    __tablename__ = "batch_symbol_runs"
    __table_args__ = (Index("ix_batch_symbol_runs_batch_symbol", "batch_run_id", "symbol"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    batch_run_id: Mapped[str] = mapped_column(ForeignKey("batch_runs.id"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class SetupEventRow(Base):
    __tablename__ = "setup_events"
    __table_args__ = (Index("ix_setup_events_setup_known", "setup_id", "known_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    setup_id: Mapped[str] = mapped_column(String(36), nullable=False)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ScannerRunRow(Base):
    __tablename__ = "scanner_runs"
    __table_args__ = (Index("ix_scanner_runs_config_started", "config_hash", "started_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class DetectorCheckpointRow(Base):
    __tablename__ = "detector_checkpoints"
    __table_args__ = (Index("ix_checkpoints_config_updated", "config_hash", "updated_at"),)

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ScannerEventRow(Base):
    __tablename__ = "scanner_events"
    __table_args__ = (Index("ix_scanner_events_market_known", "symbol", "event_type", "known_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class AlertDeliveryRow(Base):
    __tablename__ = "alert_deliveries"
    __table_args__ = (
        Index("ux_alert_delivery_dedup", "dedup_key", unique=True),
        Index(
            "ix_alert_delivery_status_retry",
            "status",
            "next_retry_at",
            "attempts",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dedup_key: Mapped[str] = mapped_column(String(192), nullable=False)
    event_id: Mapped[str] = mapped_column(ForeignKey("scanner_events.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    permanently_failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class UniverseSnapshotRow(Base):
    __tablename__ = "universe_snapshots"
    __table_args__ = (Index("ix_universe_snapshots_run", "run_id", "captured_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class LiveScannerRunRow(Base):
    __tablename__ = "live_scanner_runs"
    __table_args__ = (Index("ix_live_runs_started", "started_at", "status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class LiveSymbolRunRow(Base):
    __tablename__ = "live_symbol_runs"
    __table_args__ = (Index("ix_live_symbol_run", "run_id", "symbol"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("live_scanner_runs.id"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
