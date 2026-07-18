from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from htf_scanner.domain.enums import H4ReactionStatus, H4TouchType, SetupSide


class H4TouchPhase(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    setup_id: UUID
    symbol: str
    side: SetupSide
    first_touch_open_time: datetime
    first_touch_close_time: datetime
    last_touch_close_time: datetime
    deepest_touch_close_time: datetime
    deepest_penetration_price: Decimal
    penetration_price: Decimal = Field(ge=0)
    penetration_fraction: float = Field(ge=0)
    penetration_atr: float = Field(ge=0)
    maximum_adverse_excursion: Decimal = Field(ge=0)
    close_location: float
    bars_from_activation: int = Field(ge=0)
    bars_in_zone: int = Field(ge=1)
    duration_hours: float = Field(ge=0)
    primary_touch_type: H4TouchType
    touch_flags: dict[str, bool]
    pre_activation_mitigation_fraction: float = Field(ge=0)
    post_activation_touch_fraction: float = Field(ge=0)
    invalidated: bool = False
    config_hash: str


class H4ReactionCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    sequence_key: str
    setup_id: UUID
    touch_phase_id: UUID
    symbol: str
    side: SetupSide
    displacement_id: UUID | None = None
    structure_break_id: UUID | None = None
    broken_internal_swing_id: UUID | None = None
    h4_fvg_id: UUID | None = None
    sequence_bars: int = Field(ge=1)
    known_at: datetime
    hard_gates: dict[str, bool]
    failed_hard_gates: list[str]
    score_components: dict[str, float]
    total_score: float
    canonical: bool = False


class H4MergedCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    setup_id: UUID
    touch_phase_id: UUID
    candidate_id: UUID
    merged_into_candidate_id: UUID
    known_at: datetime
    reason: str = "MERGED_INTO_CANONICAL_H4_REACTION"


class H4RejectedCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    setup_id: UUID
    touch_phase_id: UUID
    known_at: datetime
    reasons: list[str]
    diagnostics: dict[str, str | float | int | bool | None]


class H4ReactionTransition(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    reaction_id: UUID
    setup_id: UUID
    from_status: H4ReactionStatus
    to_status: H4ReactionStatus
    formed_at: datetime
    known_at: datetime
    bar_index: int = Field(ge=0)
    reason: str


class H4Reaction(BaseModel):
    """Canonical causal H4 reaction sequence for one D1 setup."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    setup_id: UUID
    symbol: str = ""
    side: SetupSide = SetupSide.SHORT
    status: H4ReactionStatus = H4ReactionStatus.WAITING_FOR_TOUCH
    zone_id: UUID | None = None
    touch_phase_id: UUID | None = None
    touch_type: H4TouchType | None = None
    touch_open_time: datetime | None = None
    touch_close_time: datetime | None = None
    touch_at: datetime | None = None
    formed_at: datetime | None = None
    known_at: datetime | None = None
    first_reaction_at: datetime | None = None
    confirmed_at: datetime | None = None
    invalidated_at: datetime | None = None
    expired_at: datetime | None = None
    entry_price_reference: Decimal | None = None
    reaction_extreme_price: Decimal | None = None
    penetration_ratio: float = Field(default=0.0, ge=0, le=1)
    reaction_score: float = 0.0
    score_components: dict[str, float] = Field(default_factory=dict)
    invalidation_reason: str | None = None
    displacement_id: UUID | None = None
    structure_break_id: UUID | None = None
    h4_fvg_id: UUID | None = None
    config_hash: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    features: dict[str, float | int | bool | None] = Field(default_factory=dict)

    @model_validator(mode="after")
    def normalize_legacy_times(self) -> "H4Reaction":
        touch = self.touch_close_time or self.touch_at
        formed = self.formed_at or self.touch_open_time or touch
        known = self.known_at or self.confirmed_at or self.first_reaction_at or touch
        if formed is None or known is None:
            raise ValueError("reaction requires causal formed_at and known_at timestamps")
        if touch is None and self.status not in {
            H4ReactionStatus.INVALIDATED,
            H4ReactionStatus.EXPIRED,
        }:
            raise ValueError("a non-terminal reaction requires a causal touch timestamp")
        object.__setattr__(self, "touch_at", touch)
        object.__setattr__(self, "touch_close_time", touch)
        object.__setattr__(self, "formed_at", formed)
        object.__setattr__(self, "known_at", known)
        return self
