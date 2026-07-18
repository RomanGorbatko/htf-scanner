import numpy as np

from htf_scanner.indicators.atr import true_range, wilder_atr


def test_wilder_atr_uses_sma_seed_then_recursive_smoothing() -> None:
    high = np.array([10.0, 12.0, 13.0, 15.0])
    low = np.array([8.0, 9.0, 11.0, 12.0])
    close = np.array([9.0, 11.0, 12.0, 14.0])

    ranges = true_range(high, low, close)
    atr = wilder_atr(high, low, close, period=3)

    np.testing.assert_allclose(ranges, [2.0, 3.0, 2.0, 3.0])
    assert np.isnan(atr[0]) and np.isnan(atr[1])
    np.testing.assert_allclose(atr[2:], [7 / 3, 23 / 9])


def test_atr_rejects_mismatched_arrays() -> None:
    with np.testing.assert_raises(ValueError):
        true_range(np.array([1.0]), np.array([]), np.array([1.0]))
