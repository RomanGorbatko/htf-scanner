from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from htf_scanner.domain.enums import SetupSide


class ProductionEventType(StrEnum):
    D1_SETUP_ACTIVE = "D1_SETUP_ACTIVE"
    D1_SETUP_INVALIDATED = "D1_SETUP_INVALIDATED"
    H4_ZONE_TOUCHED = "H4_ZONE_TOUCHED"
    H4_EARLY_REACTION = "H4_EARLY_REACTION"
    H4_REACTION_CONFIRMED = "H4_REACTION_CONFIRMED"
    H4_REACTION_INVALIDATED = "H4_REACTION_INVALIDATED"
    H4_REACTION_EXPIRED = "H4_REACTION_EXPIRED"


class SymbolScanStatus(StrEnum):
    SUCCESS = "SUCCESS"
    NO_NEW_DATA = "NO_NEW_DATA"
    FETCH_ERROR = "FETCH_ERROR"
    DATA_ERROR = "DATA_ERROR"
    DETECTOR_ERROR = "DETECTOR_ERROR"
    ALERT_ERROR = "ALERT_ERROR"


class LiveRunStatus(StrEnum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    SKIPPED_LOCKED = "SKIPPED_LOCKED"


class AlertDeliveryStatus(StrEnum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    PERMANENTLY_FAILED = "PERMANENTLY_FAILED"


class MarketInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    quote_asset: str
    contract_type: str
    active: bool
    onboard_at: datetime
    quote_volume_24h: float = Field(ge=0)


class ExchangeMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str
    server_time: datetime
    markets: int = Field(ge=0)
    raw_version: str | None = None


class ScannerEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    event_type: ProductionEventType
    entity_id: UUID
    transition_id: UUID | None = None
    symbol: str
    side: SetupSide
    formed_at: datetime
    known_at: datetime
    config_hash: str
    payload: dict[str, Any] = Field(default_factory=dict)


class AlertDelivery(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    dedup_key: str
    event_id: UUID
    status: AlertDeliveryStatus
    attempts: int = Field(default=0, ge=0)
    created_at: datetime
    updated_at: datetime
    next_retry_at: datetime | None = None
    sent_at: datetime | None = None
    permanently_failed_at: datetime | None = None
    last_error: str | None = None
    provider_message_id: str | None = None


class DetectorCheckpoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    config_hash: str
    scanner_version: str
    last_d1_close: datetime | None = None
    last_h4_close: datetime | None = None
    initialized_at: datetime
    updated_at: datetime
    state: dict[str, Any]


class UniverseSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    run_id: UUID
    captured_at: datetime
    config_hash: str
    markets: list[MarketInfo]


class LiveScannerRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    config_hash: str
    started_at: datetime
    completed_at: datetime | None = None
    status: LiveRunStatus
    provider: str
    counts: dict[str, int] = Field(default_factory=dict)
    timings_ms: dict[str, float] = Field(default_factory=dict)
    error: str | None = None


class LiveSymbolRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    run_id: UUID
    symbol: str
    status: SymbolScanStatus
    started_at: datetime
    completed_at: datetime
    new_d1_candles: int = Field(default=0, ge=0)
    new_h4_candles: int = Field(default=0, ge=0)
    new_d1_setups: int = Field(default=0, ge=0)
    new_h4_reactions: int = Field(default=0, ge=0)
    alerts_sent: int = Field(default=0, ge=0)
    alerts_failed: int = Field(default=0, ge=0)
    timings_ms: dict[str, float] = Field(default_factory=dict)
    diagnostics: list[str] = Field(default_factory=list)
    error: str | None = None
