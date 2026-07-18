from dataclasses import dataclass
from decimal import Decimal
from math import isfinite
from uuid import NAMESPACE_URL, uuid5

from htf_scanner.config import FvgConfig
from htf_scanner.detectors.fvg_detector import penetration_ratio
from htf_scanner.domain.candle import Candle
from htf_scanner.domain.enums import FvgSide, FvgStatus
from htf_scanner.domain.fvg import FairValueGap


@dataclass
class IncrementalFvgTracker:
    config: FvgConfig
    fvgs: list[FairValueGap]
    formed_indices: dict[str, int]

    @classmethod
    def empty(cls, config: FvgConfig) -> "IncrementalFvgTracker":
        return cls(config=config, fvgs=[], formed_indices={})

    def update(self, candles: list[Candle], atr: float) -> FairValueGap | None:
        current_index = len(candles) - 1
        current = candles[current_index]
        updated: list[FairValueGap] = []
        for fvg in self.fvgs:
            formed_index = self.formed_indices[str(fvg.id)]
            if formed_index < current_index:
                fvg = self._advance(fvg, current, current_index - formed_index)
            updated.append(fvg)
        self.fvgs = updated
        created = self._create(candles, atr)
        if created is not None:
            self.fvgs.append(created)
            self.formed_indices[str(created.id)] = current_index
        return created

    def _advance(self, fvg: FairValueGap, candle: Candle, age: int) -> FairValueGap:
        if fvg.status in {FvgStatus.INVALIDATED, FvgStatus.EXPIRED, FvgStatus.FULLY_FILLED}:
            return fvg
        if age > self.config.expire_after_d1_bars:
            return fvg.model_copy(
                update={"status": FvgStatus.EXPIRED, "expired_at": candle.close_time}
            )
        touched = candle.high >= fvg.lower and candle.low <= fvg.upper
        ratio = penetration_ratio(fvg, candle) if touched else 0.0
        maximum_fill = max(fvg.fill_ratio, ratio)
        updates: dict[str, object] = {"fill_ratio": maximum_fill}
        if touched and fvg.first_touch_at is None:
            updates["first_touch_at"] = candle.close_time
        for threshold, field in (
            (0.25, "first_25_fill_at"),
            (0.5, "midpoint_fill_at"),
            (0.75, "first_75_fill_at"),
            (1.0, "full_fill_at"),
        ):
            if maximum_fill >= threshold and getattr(fvg, field) is None:
                updates[field] = candle.close_time
        invalidated = (fvg.side == FvgSide.BEARISH and candle.close > fvg.upper) or (
            fvg.side == FvgSide.BULLISH and candle.close < fvg.lower
        )
        if invalidated:
            updates.update({"status": FvgStatus.INVALIDATED, "invalidated_at": candle.close_time})
        elif maximum_fill >= 1.0:
            updates["status"] = FvgStatus.FULLY_FILLED
        elif maximum_fill > 0:
            updates["status"] = FvgStatus.PARTIALLY_FILLED
        return fvg.model_copy(update=updates)

    def _create(self, candles: list[Candle], atr: float) -> FairValueGap | None:
        if len(candles) < 3 or not isfinite(atr) or atr <= 0:
            return None
        first, source, current = candles[-3], candles[-2], candles[-1]
        if current.high < first.low:
            side, lower, upper = FvgSide.BEARISH, current.high, first.low
        elif current.low > first.high:
            side, lower, upper = FvgSide.BULLISH, first.high, current.low
        else:
            return None
        size = upper - lower
        size_atr = float(size) / atr
        if not self.config.minimum_size_atr <= size_atr <= self.config.maximum_size_atr:
            return None
        identity = ":".join(
            [
                current.symbol,
                current.timeframe,
                side.value,
                current.open_time.isoformat(),
                str(lower),
                str(upper),
            ]
        )
        return FairValueGap(
            id=uuid5(NAMESPACE_URL, identity),
            symbol=current.symbol,
            timeframe=current.timeframe,
            side=side,
            formed_at=current.open_time,
            known_at=current.close_time,
            lower=lower,
            upper=upper,
            midpoint=(lower + upper) / Decimal("2"),
            size=size,
            size_atr=size_atr,
            source_candle_time=source.open_time,
        )

    def export_state(self) -> dict[str, object]:
        return {
            "fvgs": [item.model_dump(mode="json") for item in self.fvgs],
            "formed_indices": self.formed_indices,
        }

    def restore_state(self, payload: dict[str, object]) -> None:
        raw_fvgs = payload.get("fvgs", [])
        raw_indices = payload.get("formed_indices", {})
        if not isinstance(raw_fvgs, list) or not isinstance(raw_indices, dict):
            raise ValueError("invalid FVG tracker state")
        self.fvgs = [FairValueGap.model_validate(item) for item in raw_fvgs]
        self.formed_indices = {str(key): int(value) for key, value in raw_indices.items()}
