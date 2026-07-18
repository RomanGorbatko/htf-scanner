from pathlib import Path

from htf_scanner.batch import scan_offline_universe
from htf_scanner.config import AppConfig, AtrConfig, BatchScanConfig
from htf_scanner.data.cache import CandleFileCache
from htf_scanner.pipeline import analyze_symbol
from tests.conftest import make_candle
from tests.unit.test_h4_reaction_engine import h4


def seed(cache: CandleFileCache, symbol: str) -> None:
    d1 = [make_candle(index, "10", "11", "9", "10", symbol=symbol) for index in range(5)]
    h4_candles = [
        item.model_copy(update={"symbol": symbol})
        for item in [h4(index, "10", "11", "9", "10") for index in range(8)]
    ]
    cache.write(symbol, "1d", d1)
    cache.write(symbol, "4h", h4_candles)


def batch_config() -> AppConfig:
    return AppConfig(
        atr=AtrConfig(period=2),
        batch_scan=BatchScanConfig(minimum_d1_candles=3, minimum_h4_candles=3),
    )


def test_symbol_failure_is_isolated_and_order_is_stable(tmp_path: Path) -> None:
    cache = CandleFileCache(tmp_path)
    seed(cache, "GOODUSDT")
    first = scan_offline_universe(["MISSINGUSDT", "GOODUSDT"], cache, batch_config(), "hash")
    second = scan_offline_universe(["GOODUSDT", "MISSINGUSDT"], cache, batch_config(), "hash")
    assert list(first.analyses) == ["GOODUSDT"]
    assert list(first.errors) == ["MISSINGUSDT"]
    assert [item.symbol for item in first.symbol_runs] == ["GOODUSDT", "MISSINGUSDT"]
    assert first.run.manifest_hash == second.run.manifest_hash
    assert first.run.id == second.run.id


def test_batch_counts_match_single_symbol_analysis(tmp_path: Path) -> None:
    cache = CandleFileCache(tmp_path)
    seed(cache, "GOODUSDT")
    config = batch_config()
    batch = scan_offline_universe(["GOODUSDT"], cache, config, "hash")
    single = analyze_symbol(
        cache.read("GOODUSDT", "1d"),
        cache.read("GOODUSDT", "4h"),
        config,
        "hash",
        strict_data=True,
    )
    row = batch.symbol_runs[0]
    assert row.setup_count == len(single.d1.setups)
    assert row.reaction_count == len(single.h4.reactions)
    assert row.outcome_count == len(single.outcomes.outcomes)
