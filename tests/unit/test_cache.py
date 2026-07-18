from htf_scanner.data.cache import CandleFileCache
from tests.conftest import make_candle


def test_file_cache_is_idempotent(tmp_path) -> None:  # type: ignore[no-untyped-def]
    cache = CandleFileCache(tmp_path)
    candles = [make_candle(0, "1", "2", "0.5", "1.5")]

    cache.write("TESTUSDT", "1d", candles)
    cache.write("TESTUSDT", "1d", candles)

    assert cache.read("TESTUSDT", "1d") == candles
