from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from htf_scanner.domain.enums import (
    Direction,
    LiquidityContextType,
    LiquidityInteractionType,
)


class LiquidityInteraction(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    external_level_id: UUID
    reference_swing_id: UUID
    symbol: str
    timeframe: str
    direction: Direction
    event_type: LiquidityInteractionType
    level_price: Decimal
    formed_at: datetime
    known_at: datetime
    candle_time: datetime
    bar_index: int = Field(ge=0)
    excursion_price: Decimal = Field(ge=0)
    excursion_atr: float = Field(ge=0)
    close_relative_to_level: Decimal
    closes_beyond_level: int = Field(ge=0)
    maximum_acceptance_distance_atr: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_causality(self) -> "LiquidityInteraction":
        if any(
            timestamp.tzinfo is None or timestamp.utcoffset() != timedelta(0)
            for timestamp in (self.formed_at, self.known_at, self.candle_time)
        ):
            raise ValueError("interaction timestamps must be UTC-aware")
        if self.known_at < self.formed_at:
            raise ValueError("interaction known_at must not precede formed_at")
        return self


class LiquiditySequence(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    sequence_key: str
    symbol: str
    timeframe: str
    direction: Direction
    classification: LiquidityContextType
    external_reference_swing_id: UUID | None = None
    interaction_ids: list[UUID] = Field(default_factory=list)
    sweep_interaction_id: UUID | None = None
    retracement_swing_id: UUID | None = None
    attempt_swing_id: UUID | None = None
    broken_internal_swing_id: UUID | None = None
    structure_break_id: UUID | None = None
    displacement_id: UUID
    fvg_id: UUID | None = None
    formed_at: datetime
    known_at: datetime
    hard_gates: dict[str, bool]
    failed_hard_gates: list[str]
    soft_feature_values: dict[str, float | int | bool | None]
    score_penalties: dict[str, float]
    score_components: dict[str, float]
    total_score: float

    @model_validator(mode="after")
    def validate_causality(self) -> "LiquiditySequence":
        if any(
            timestamp.tzinfo is None or timestamp.utcoffset() != timedelta(0)
            for timestamp in (self.formed_at, self.known_at)
        ):
            raise ValueError("liquidity sequence timestamps must be UTC-aware")
        if self.known_at < self.formed_at:
            raise ValueError("sequence known_at must not precede formed_at")
        return self


class LiquidityContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    displacement_id: UUID
    symbol: str
    timeframe: str
    reversal_direction: Direction
    classification: LiquidityContextType
    formed_at: datetime
    known_at: datetime
    external_reference_swing_id: UUID | None = None
    external_reference_price: Decimal | None = None
    external_reference_formed_at: datetime | None = None
    attempt_swing_id: UUID | None = None
    attempt_price: Decimal | None = None
    attempt_formed_at: datetime | None = None
    retracement_swing_id: UUID | None = None
    retracement_price: Decimal | None = None
    retracement_formed_at: datetime | None = None
    structure_break_id: UUID | None = None
    liquidity_sequence_id: UUID | None = None
    interaction_ids: list[UUID] = Field(default_factory=list)
    sweep_interaction_id: UUID | None = None
    sweep: bool = False
    accepted_breakout: bool = False
    external_liquidity_remained: bool | None = None
    score: float = Field(ge=0)
    component_scores: dict[str, float]
    features: dict[str, float | int | bool | None]
    hard_gates: dict[str, bool] = Field(default_factory=dict)
    failed_hard_gates: list[str] = Field(default_factory=list)
    score_penalties: dict[str, float] = Field(default_factory=dict)
