from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SetupEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    setup_id: UUID
    event_type: str
    event_time: datetime
    known_at: datetime
    payload: dict[str, str | float | int | bool | None]
    scanner_version: str
    config_hash: str
