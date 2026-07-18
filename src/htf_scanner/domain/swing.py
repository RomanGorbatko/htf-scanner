from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from htf_scanner.domain.enums import SwingSide, SwingStatus


class SwingPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    symbol: str
    timeframe: str
    side: SwingSide
    formed_at: datetime
    known_at: datetime
    price: Decimal
    atr_at_formation: Decimal
    confirmation_move_atr: float = Field(ge=0)
    status: SwingStatus = SwingStatus.CONFIRMED
    bar_index: int = Field(ge=0)
    confirmation_bar_index: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_causality(self) -> "SwingPoint":
        if self.known_at < self.formed_at:
            raise ValueError("known_at must not precede formed_at")
        if self.confirmation_bar_index < self.bar_index:
            raise ValueError("confirmation bar must not precede the extreme bar")
        if self.atr_at_formation <= 0:
            raise ValueError("ATR at swing formation must be positive")
        return self
