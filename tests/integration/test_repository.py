from htf_scanner.storage.database import create_database_engine
from htf_scanner.storage.repository import CandleRepository
from tests.conftest import make_candle


def test_candle_roundtrip_and_idempotent_upsert(tmp_path) -> None:  # type: ignore[no-untyped-def]
    engine = create_database_engine(f"sqlite:///{tmp_path / 'test.db'}")
    repository = CandleRepository(engine)
    candle = make_candle(0, "1", "2", "0.5", "1.5")

    repository.upsert_many([candle])
    repository.upsert_many([candle])
    loaded = repository.list_range(
        candle.symbol,
        candle.timeframe,
        candle.open_time,
        candle.close_time,
    )

    assert loaded == [candle]
    engine.dispose()
