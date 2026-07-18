from datetime import datetime
from typing import Protocol, runtime_checkable

from htf_scanner.domain.candle import Candle
from htf_scanner.domain.production import ExchangeMetadata, MarketInfo


@runtime_checkable
class MarketDataProvider(Protocol):
    """Exchange-neutral contract consumed by production orchestration."""

    def discover_markets(self) -> list[MarketInfo]: ...

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Candle]: ...

    def fetch_latest_closed_candle(self, symbol: str, timeframe: str) -> Candle | None: ...

    def server_time(self) -> datetime: ...

    def exchange_metadata(self) -> ExchangeMetadata: ...

    def close(self) -> None: ...
