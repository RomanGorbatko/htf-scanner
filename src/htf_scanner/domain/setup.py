from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from htf_scanner.domain.enums import LiquidityContextType, SetupSide, SetupStatus


class HTFSetup(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    symbol: str
    timeframe: str
    side: SetupSide
    formed_at: datetime
    known_at: datetime
    fvg_id: UUID
    displacement_id: UUID
    liquidity_context_id: UUID
    liquidity_sequence_id: UUID | None = None
    canonical_candidate_id: UUID | None = None
    liquidity_interaction_ids: list[UUID] = Field(default_factory=list)
    sweep_interaction_id: UUID | None = None
    structure_break_id: UUID | None = None
    status: SetupStatus = SetupStatus.ACTIVE
    liquidity_classification: LiquidityContextType
    external_liquidity_remained: bool | None = None
    quality_score: float = Field(ge=0)
    context_score: float = Field(ge=0)
    displacement_score: float = Field(ge=0)
    fvg_score: float = Field(ge=0)
    structure_score: float = Field(ge=0)
    score_components: dict[str, float]
    invalidation_price: Decimal
    formed_bar_index: int = Field(ge=0)
    known_bar_index: int = Field(ge=0)
    expires_after_bar_index: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_causality(self) -> "HTFSetup":
        if self.known_at < self.formed_at:
            raise ValueError("known_at must not precede formed_at")
        component_total = sum(self.score_components.values())
        if abs(component_total - self.quality_score) > 1e-9:
            raise ValueError("quality score must equal its component sum")
        if self.known_bar_index < self.formed_bar_index:
            raise ValueError("known bar must not precede formed bar")
        if self.expires_after_bar_index <= self.known_bar_index:
            raise ValueError("expiry bar must follow the known bar")
        return self


class HTFSetupTransition(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    setup_id: UUID
    from_status: SetupStatus
    to_status: SetupStatus
    known_at: datetime
    bar_index: int = Field(ge=0)
    reason: str


class RejectedSetupCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    symbol: str
    timeframe: str
    side: SetupSide
    displacement_id: UUID
    fvg_id: UUID | None = None
    liquidity_context_id: UUID | None = None
    rejected_at: datetime
    bar_index: int = Field(ge=0)
    reasons: list[str]
    hard_rejection_reasons: list[str] = Field(default_factory=list)
    score_penalties: dict[str, float] = Field(default_factory=dict)
    failed_hard_gates: list[str] = Field(default_factory=list)
    soft_feature_values: dict[str, float | int | bool | None] = Field(default_factory=dict)
    diagnostics: dict[str, str | float | int | bool | None]


class D1SetupCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    sequence_key: str
    symbol: str
    timeframe: str
    side: SetupSide
    liquidity_sequence_id: UUID | None = None
    liquidity_context_id: UUID | None = None
    external_reference_swing_id: UUID | None = None
    retracement_swing_id: UUID | None = None
    attempt_swing_id: UUID | None = None
    broken_internal_swing_id: UUID | None = None
    structure_break_id: UUID | None = None
    displacement_id: UUID
    fvg_id: UUID | None = None
    known_at: datetime
    bar_index: int = Field(ge=0)
    sequence_bars: int = Field(ge=1)
    canonical: bool = False
    hard_rejection_reasons: list[str]
    failed_hard_gates: list[str]
    soft_feature_values: dict[str, float | int | bool | None]
    score_penalties: dict[str, float]
    score_components: dict[str, float]
    total_score: float

    @model_validator(mode="after")
    def validate_known_at(self) -> "D1SetupCandidate":
        if self.known_at.tzinfo is None or self.known_at.utcoffset() != timedelta(0):
            raise ValueError("candidate known_at must be UTC-aware")
        return self


class MergedSetupCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    sequence_key: str
    symbol: str
    timeframe: str
    side: SetupSide
    displacement_id: UUID
    merged_into_candidate_id: UUID
    known_at: datetime
    reason: str = "MERGED_INTO_CANONICAL_CANDIDATE"

    @model_validator(mode="after")
    def validate_known_at(self) -> "MergedSetupCandidate":
        if self.known_at.tzinfo is None or self.known_at.utcoffset() != timedelta(0):
            raise ValueError("merged candidate known_at must be UTC-aware")
        return self
