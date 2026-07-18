from datetime import datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from htf_scanner.domain.candle import Candle


def test_candle_rejects_naive_timestamps() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        Candle(
            symbol="testusdt",
            timeframe="1d",
            open_time=datetime(2026, 1, 1),
            close_time=datetime(2026, 1, 2),
            open=Decimal("1"),
            high=Decimal("2"),
            low=Decimal("0.5"),
            close=Decimal("1.5"),
            volume=Decimal("10"),
        )
