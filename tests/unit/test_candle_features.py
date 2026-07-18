from htf_scanner.indicators.candle_features import calculate_candle_features
from tests.conftest import make_candle


def test_candle_features_handle_zero_range() -> None:
    candle = make_candle(0, "10", "10", "10", "10")

    features = calculate_candle_features([candle], atr_period=1).iloc[0]

    assert features["range"] == 0
    assert features["body_ratio"] == 0
    assert features["close_location"] == 0.5
