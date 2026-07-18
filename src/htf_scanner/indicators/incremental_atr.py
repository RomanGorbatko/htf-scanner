from dataclasses import dataclass, field
from decimal import Decimal
from math import nan

import numpy as np

from htf_scanner.domain.candle import Candle


@dataclass
class WilderAtrState:
    period: int
    previous_close: Decimal | None = None
    seed_ranges: list[float] = field(default_factory=list)
    value: float | None = None

    def update(self, candle: Candle) -> float:
        high = float(candle.high)
        low = float(candle.low)
        high_low = high - low
        if self.previous_close is None:
            true_range = high_low
        else:
            previous_close = float(self.previous_close)
            true_range = max(
                high_low,
                abs(high - previous_close),
                abs(low - previous_close),
            )
        self.previous_close = candle.close
        if self.value is None:
            self.seed_ranges.append(true_range)
            if len(self.seed_ranges) == self.period:
                self.value = float(np.mean(np.array(self.seed_ranges, dtype=np.float64)))
            return self.value if self.value is not None else nan
        self.value = ((self.value * (self.period - 1)) + true_range) / self.period
        return self.value

    def snapshot(self) -> dict[str, object]:
        return {
            "period": self.period,
            "previous_close": str(self.previous_close) if self.previous_close is not None else None,
            "seed_ranges": self.seed_ranges,
            "value": self.value,
        }

    @classmethod
    def restore(cls, payload: dict[str, object]) -> "WilderAtrState":
        previous = payload.get("previous_close")
        ranges = payload.get("seed_ranges", [])
        if not isinstance(ranges, list):
            raise ValueError("ATR seed_ranges state must be a list")
        value = payload.get("value")
        return cls(
            period=int(str(payload["period"])),
            previous_close=Decimal(str(previous)) if previous is not None else None,
            seed_ranges=[float(str(item)) for item in ranges],
            value=float(str(value)) if value is not None else None,
        )
