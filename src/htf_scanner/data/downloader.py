from datetime import datetime

from htf_scanner.data.binance_rest import BinanceRestClient
from htf_scanner.data.cache import CandleFileCache
from htf_scanner.domain.candle import Candle
from htf_scanner.storage.repository import CandleRepository


class CandleDownloader:
    def __init__(
        self,
        client: BinanceRestClient,
        repository: CandleRepository,
        file_cache: CandleFileCache,
    ) -> None:
        self._client = client
        self._repository = repository
        self._file_cache = file_cache

    def download(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> list[Candle]:
        candles = self._client.fetch_klines(symbol, timeframe, start, end)
        self._repository.upsert_many(candles)
        self._file_cache.write(symbol, timeframe, candles)
        return candles
