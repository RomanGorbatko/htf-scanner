from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from htf_scanner.domain.enums import (
    Direction,
    StructureBreakKind,
    StructureLevelType,
)


class StructureBreak(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    symbol: str
    timeframe: str
    direction: Direction
    kind: StructureBreakKind
    level_type: StructureLevelType
    broken_swing_id: UUID
    level_price: Decimal
    break_price: Decimal
    formed_at: datetime
    known_at: datetime
    break_distance_atr: float = Field(ge=0)
    bar_index: int = Field(ge=0)


class StructurePromotion(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    symbol: str
    timeframe: str
    direction: Direction
    promoted_swing_id: UUID
    replaced_external_swing_id: UUID | None = None
    protected_swing_id: UUID
    caused_by_break_id: UUID
    promoted_at: datetime
    bar_index: int = Field(ge=0)


class MarketStructureSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    timeframe: str
    known_at: datetime
    trend: Direction | None
    active_leg: Direction | None
    internal_high_id: UUID | None = None
    internal_low_id: UUID | None = None
    external_high_id: UUID | None = None
    external_low_id: UUID | None = None
    internal_high: Decimal | None = None
    internal_low: Decimal | None = None
    external_high: Decimal | None = None
    external_low: Decimal | None = None
    protected_high_id: UUID | None = None
    protected_low_id: UUID | None = None
    protected_high: Decimal | None = None
    protected_low: Decimal | None = None
