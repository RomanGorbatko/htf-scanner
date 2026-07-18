from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class Candle(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    timeframe: str
    open_time: datetime
    close_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    quote_volume: Decimal | None = None
    trades: int | None = None
    is_closed: bool = True

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, symbol: str) -> str:
        return symbol.upper()

    @field_validator("open_time", "close_time")
    @classmethod
    def normalize_timestamp(cls, timestamp: datetime) -> datetime:
        if timestamp.tzinfo is None:
            raise ValueError("candle timestamps must be timezone-aware")
        return timestamp.astimezone(UTC)

    @model_validator(mode="after")
    def validate_market_data(self) -> "Candle":
        if self.close_time <= self.open_time:
            raise ValueError("close_time must be after open_time")
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("OHLC values are inconsistent")
        if self.low > self.high:
            raise ValueError("low must not exceed high")
        return self
