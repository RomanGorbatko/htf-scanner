from htf_scanner.config import FvgConfig
from htf_scanner.detectors.fvg_detector import detect_fvgs
from htf_scanner.domain.enums import FvgSide, FvgStatus
from tests.conftest import make_candle


def permissive_config() -> FvgConfig:
    return FvgConfig(minimum_size_atr=0, maximum_size_atr=100, expire_after_d1_bars=90)


def test_detects_bearish_fvg_and_tracks_fill_and_invalidation() -> None:
    candles = [
        make_candle(0, "11", "12", "10", "11"),
        make_candle(1, "11", "11", "8", "9"),
        make_candle(2, "9", "9", "7", "8"),
        make_candle(3, "8", "9.5", "7.5", "8.5"),
        make_candle(4, "8.5", "10.2", "8", "10.1"),
    ]

    fvgs = detect_fvgs(candles, atr_period=2, config=permissive_config())
    bearish = next(fvg for fvg in fvgs if fvg.side == FvgSide.BEARISH)

    assert str(bearish.lower) == "9"
    assert str(bearish.upper) == "10"
    assert bearish.known_at == candles[2].close_time
    assert bearish.fill_ratio == 1.0
    assert bearish.first_touch_at == candles[3].close_time
    assert bearish.midpoint_fill_at == candles[3].close_time
    assert bearish.full_fill_at == candles[4].close_time
    assert bearish.invalidated_at == candles[4].close_time
    assert bearish.status == FvgStatus.INVALIDATED


def test_detects_bullish_fvg_symmetrically() -> None:
    candles = [
        make_candle(0, "8", "9", "7", "8"),
        make_candle(1, "8", "11", "8", "10"),
        make_candle(2, "10", "12", "10", "11"),
        make_candle(3, "11", "11.5", "9.5", "10"),
    ]

    fvgs = detect_fvgs(candles, atr_period=2, config=permissive_config())
    bullish = next(fvg for fvg in fvgs if fvg.side == FvgSide.BULLISH)

    assert str(bullish.lower) == "9"
    assert str(bullish.upper) == "10"
    assert bullish.fill_ratio == 0.5
    assert bullish.status == FvgStatus.PARTIALLY_FILLED


def test_detection_is_deterministic() -> None:
    candles = [
        make_candle(0, "11", "12", "10", "11"),
        make_candle(1, "11", "11", "8", "9"),
        make_candle(2, "9", "9", "7", "8"),
    ]

    first = detect_fvgs(candles, atr_period=2, config=permissive_config())
    second = detect_fvgs(candles, atr_period=2, config=permissive_config())

    assert [fvg.id for fvg in first] == [fvg.id for fvg in second]
