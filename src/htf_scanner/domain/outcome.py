from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from htf_scanner.domain.enums import ReactionOutcomeLabel, SetupSide


class SetupOutcome(BaseModel):
    """Legacy setup-level outcome persistence contract."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    setup_id: UUID
    anchor_type: str
    anchor_at: datetime
    evaluated_at: datetime
    metrics: dict[str, float | int | bool | None]
    labels: dict[str, bool]


class ReactionOutcome(BaseModel):
    """Immutable causal outcome snapshot at one configured H4 horizon."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    reaction_id: UUID
    setup_id: UUID
    symbol: str
    side: SetupSide
    horizon_bars: int = Field(ge=1)
    reference_price: Decimal
    atr_at_confirmation: Decimal = Field(gt=0)
    confirmed_at: datetime
    evaluated_at: datetime
    observed_bars: int = Field(ge=0)
    mfe_price: Decimal = Field(ge=0)
    mfe_atr: float = Field(ge=0)
    mae_price: Decimal = Field(ge=0)
    mae_atr: float = Field(ge=0)
    bars_to_mfe: int | None = Field(default=None, ge=1)
    bars_to_mae: int | None = Field(default=None, ge=1)
    hours_to_mfe: float | None = Field(default=None, ge=0)
    hours_to_mae: float | None = Field(default=None, ge=0)
    labels: list[ReactionOutcomeLabel]
    config_hash: str


class ReactionTargetOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    reaction_id: UUID
    outcome_id: UUID
    setup_id: UUID
    target_type: str
    target_price: Decimal
    known_at: datetime
    horizon_bars: int = Field(ge=1)
    reached_at: datetime | None = None
    bars_to_target: int | None = Field(default=None, ge=1)
    adverse_excursion_before_target: Decimal = Field(ge=0)
    config_hash: str


class ReactionTargetReference(BaseModel):
    model_config = ConfigDict(frozen=True)

    target_type: str
    target_price: Decimal
    known_at: datetime
