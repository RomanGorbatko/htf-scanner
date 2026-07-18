from htf_scanner.config import SwingConfig
from htf_scanner.domain.candle import Candle
from htf_scanner.indicators.candle_features import calculate_candle_features
from htf_scanner.structure.causal_swings import CausalSwingDetector, detect_causal_swings
from tests.conftest import make_candle


def swing_candles() -> list[Candle]:
    return [
        make_candle(0, "9.5", "10", "9", "9.5"),
        make_candle(1, "10", "12", "10", "11.5"),
        make_candle(2, "11", "11", "9", "9.5"),
        make_candle(3, "9", "9.5", "7", "8"),
        make_candle(4, "8", "10", "8", "9.5"),
        make_candle(5, "10", "13", "10", "12.5"),
        make_candle(6, "12", "12", "9", "9.5"),
        make_candle(7, "9", "9", "6", "6.5"),
    ]


def test_causal_swings_preserve_formed_and_known_times() -> None:
    candles = swing_candles()
    config = SwingConfig(reversal_atr=0.5, minimum_bars_between_swings=1)

    swings = detect_causal_swings(candles, atr_period=2, config=config)

    assert [swing.side.value for swing in swings] == ["high", "low", "high"]
    assert [str(swing.price) for swing in swings] == ["12", "7", "13"]
    assert swings[0].formed_at == candles[1].open_time
    assert swings[0].known_at == candles[2].close_time
    assert all(swing.formed_at < swing.known_at for swing in swings)


def test_batch_and_candle_by_candle_swings_are_identical() -> None:
    candles = swing_candles()
    config = SwingConfig(reversal_atr=0.5, minimum_bars_between_swings=1)
    batch = detect_causal_swings(candles, atr_period=2, config=config)
    features = calculate_candle_features(candles, atr_period=2)
    detector = CausalSwingDetector(config)

    incremental = [
        swing
        for index, candle in enumerate(candles)
        if (swing := detector.update(candle, float(features.iloc[index]["atr"]))) is not None
    ]

    assert incremental == batch


def test_shuffled_batch_input_is_sorted_before_atr_features() -> None:
    candles = swing_candles()
    shuffled = [candles[index] for index in [5, 1, 7, 0, 3, 6, 2, 4]]
    config = SwingConfig(reversal_atr=0.5, minimum_bars_between_swings=1)

    assert detect_causal_swings(shuffled, 2, config) == detect_causal_swings(candles, 2, config)
