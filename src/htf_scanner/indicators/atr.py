import numpy as np
import numpy.typing as npt


def true_range(
    high: npt.NDArray[np.float64],
    low: npt.NDArray[np.float64],
    close: npt.NDArray[np.float64],
) -> npt.NDArray[np.float64]:
    if not (len(high) == len(low) == len(close)):
        raise ValueError("high, low, and close arrays must have equal length")
    if len(high) == 0:
        return np.array([], dtype=np.float64)
    previous_close = np.concatenate(([np.nan], close[:-1]))
    components = np.vstack(
        (high - low, np.abs(high - previous_close), np.abs(low - previous_close))
    )
    components[1:, 0] = components[0, 0]
    return np.max(components, axis=0)


def wilder_atr(
    high: npt.NDArray[np.float64],
    low: npt.NDArray[np.float64],
    close: npt.NDArray[np.float64],
    period: int = 14,
) -> npt.NDArray[np.float64]:
    if period < 1:
        raise ValueError("ATR period must be positive")
    ranges = true_range(high, low, close)
    atr = np.full(len(ranges), np.nan, dtype=np.float64)
    if len(ranges) < period:
        return atr
    atr[period - 1] = float(np.mean(ranges[:period]))
    for index in range(period, len(ranges)):
        atr[index] = ((atr[index - 1] * (period - 1)) + ranges[index]) / period
    return atr
