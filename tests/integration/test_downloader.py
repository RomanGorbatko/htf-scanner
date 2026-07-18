from datetime import UTC, datetime, timedelta
from pathlib import Path

from htf_scanner.data.cache import CandleFileCache
from htf_scanner.data.downloader import CandleDownloader
from htf_scanner.domain.candle import Candle
from htf_scanner.storage.database import create_database_engine
from htf_scanner.storage.repository import CandleRepository
from tests.conftest import make_candle


class StubClient:
    def __init__(self, candles: list[Candle]) -> None:
        self.candles = candles

    def fetch_klines(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> list[Candle]:
        return self.candles


def test_downloader_persists_to_both_caches(tmp_path: Path) -> None:
    candle = make_candle(0, "1", "2", "0.5", "1.5")
    engine = create_database_engine(f"sqlite:///{tmp_path / 'test.db'}")
    repository = CandleRepository(engine)
    file_cache = CandleFileCache(tmp_path / "cache")
    downloader = CandleDownloader(StubClient([candle]), repository, file_cache)  # type: ignore[arg-type]

    downloaded = downloader.download(
        candle.symbol, candle.timeframe, candle.open_time, candle.open_time + timedelta(days=1)
    )

    assert downloaded == [candle]
    assert file_cache.read(candle.symbol, candle.timeframe) == [candle]
    assert repository.list_range(
        candle.symbol,
        candle.timeframe,
        candle.open_time,
        datetime(2026, 2, 1, tzinfo=UTC),
    ) == [candle]
    engine.dispose()
