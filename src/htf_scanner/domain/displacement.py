from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from htf_scanner.domain.enums import Direction


class Displacement(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    symbol: str
    timeframe: str
    direction: Direction
    start_time: datetime
    end_time: datetime
    known_at: datetime
    sequence_bars: int = Field(ge=1)
    score: float = Field(ge=0)
    body_atr: float = Field(ge=0)
    range_atr: float = Field(ge=0)
    net_move_atr: float = Field(ge=0)
    body_efficiency: float = Field(ge=0, le=1)
    directional_efficiency: float = Field(ge=0, le=1)
    close_location: float = Field(ge=0, le=1)
    structure_break: bool
    structure_break_id: UUID | None = None
    created_fvg: bool
    fvg_id: UUID | None = None
    component_scores: dict[str, float]

    @model_validator(mode="after")
    def validate_links(self) -> "Displacement":
        if self.structure_break != (self.structure_break_id is not None):
            raise ValueError("structure break flag and ID must agree")
        if self.created_fvg != (self.fvg_id is not None):
            raise ValueError("FVG flag and ID must agree")
        if self.known_at < self.end_time:
            raise ValueError("known_at must not precede displacement end time")
        return self
