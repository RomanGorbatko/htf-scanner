import numpy as np
import pandas as pd

from htf_scanner.domain.candle import Candle
from htf_scanner.indicators.atr import wilder_atr


def calculate_candle_features(candles: list[Candle], atr_period: int = 14) -> pd.DataFrame:
    if not candles:
        return pd.DataFrame()
    ordered = sorted(candles, key=lambda candle: candle.open_time)
    high = np.array([float(candle.high) for candle in ordered], dtype=np.float64)
    low = np.array([float(candle.low) for candle in ordered], dtype=np.float64)
    open_price = np.array([float(candle.open) for candle in ordered], dtype=np.float64)
    close = np.array([float(candle.close) for candle in ordered], dtype=np.float64)
    candle_range = high - low
    body = np.abs(close - open_price)
    upper_wick = high - np.maximum(open_price, close)
    lower_wick = np.minimum(open_price, close) - low
    atr = wilder_atr(high, low, close, atr_period)
    body_ratio = np.divide(body, candle_range, out=np.zeros_like(body), where=candle_range != 0)
    close_location = np.divide(
        close - low,
        candle_range,
        out=np.full_like(close, 0.5),
        where=candle_range != 0,
    )
    body_atr = np.divide(body, atr, out=np.full_like(body, np.nan), where=atr != 0)
    range_atr = np.divide(candle_range, atr, out=np.full_like(body, np.nan), where=atr != 0)
    return pd.DataFrame(
        {
            "symbol": [candle.symbol for candle in ordered],
            "timeframe": [candle.timeframe for candle in ordered],
            "open_time": [candle.open_time for candle in ordered],
            "close_time": [candle.close_time for candle in ordered],
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.array([float(candle.volume) for candle in ordered]),
            "atr": atr,
            "range": candle_range,
            "body": body,
            "upper_wick": upper_wick,
            "lower_wick": lower_wick,
            "body_ratio": body_ratio,
            "body_atr": body_atr,
            "range_atr": range_atr,
            "close_location": close_location,
            "bearish_close_strength": 1 - close_location,
        }
    )
