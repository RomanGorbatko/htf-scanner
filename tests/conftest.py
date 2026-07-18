from datetime import UTC, datetime, timedelta
from decimal import Decimal

from htf_scanner.domain.candle import Candle


def make_candle(
    day: int,
    open_price: str,
    high: str,
    low: str,
    close: str,
    *,
    symbol: str = "TESTUSDT",
    timeframe: str = "1d",
) -> Candle:
    open_time = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=day)
    interval = timedelta(days=1) if timeframe == "1d" else timedelta(hours=4)
    return Candle(
        symbol=symbol,
        timeframe=timeframe,
        open_time=open_time,
        close_time=open_time + interval - timedelta(milliseconds=1),
        open=Decimal(open_price),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal("100"),
        quote_volume=Decimal("1000"),
        trades=10,
    )
