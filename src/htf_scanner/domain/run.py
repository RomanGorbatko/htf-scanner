from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from htf_scanner.domain.enums import BatchRunStatus, ScannerRunStatus


class ScannerRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    scanner_version: str
    config_hash: str
    symbol: str
    timeframe: str
    start_at: datetime
    end_at: datetime
    started_at: datetime
    completed_at: datetime | None = None
    status: ScannerRunStatus
    counts: dict[str, int]


class BatchRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    config_hash: str
    symbols: list[str]
    started_at: datetime
    completed_at: datetime | None = None
    status: BatchRunStatus
    manifest_hash: str
    counts: dict[str, int]


class BatchSymbolRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    batch_run_id: UUID
    symbol: str
    status: BatchRunStatus
    started_at: datetime
    completed_at: datetime
    runtime_ms: int = Field(ge=0)
    d1_candles: int = Field(ge=0)
    h4_candles: int = Field(ge=0)
    setup_count: int = Field(ge=0)
    reaction_count: int = Field(ge=0)
    outcome_count: int = Field(ge=0)
    error: str | None = None
