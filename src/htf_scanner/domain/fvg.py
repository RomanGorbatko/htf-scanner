from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from htf_scanner.domain.enums import FvgSide, FvgStatus


class FairValueGap(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    symbol: str
    timeframe: str
    side: FvgSide
    formed_at: datetime
    known_at: datetime
    lower: Decimal
    upper: Decimal
    midpoint: Decimal
    size: Decimal
    size_atr: float
    source_candle_time: datetime
    displacement_score: float = 0.0
    status: FvgStatus = FvgStatus.ACTIVE
    fill_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    first_touch_at: datetime | None = None
    first_25_fill_at: datetime | None = None
    midpoint_fill_at: datetime | None = None
    first_75_fill_at: datetime | None = None
    full_fill_at: datetime | None = None
    invalidated_at: datetime | None = None
    expired_at: datetime | None = None

    @model_validator(mode="after")
    def validate_boundaries(self) -> "FairValueGap":
        if self.lower >= self.upper:
            raise ValueError("FVG lower boundary must be below upper boundary")
        if self.size != self.upper - self.lower:
            raise ValueError("FVG size does not match its boundaries")
        if self.midpoint != (self.lower + self.upper) / 2:
            raise ValueError("FVG midpoint does not match its boundaries")
        if self.known_at < self.formed_at:
            raise ValueError("known_at must not precede formed_at")
        return self
