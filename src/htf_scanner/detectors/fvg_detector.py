from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from math import isfinite
from uuid import NAMESPACE_URL, uuid5

from htf_scanner.config import FvgConfig
from htf_scanner.domain.candle import Candle
from htf_scanner.domain.enums import FvgSide, FvgStatus
from htf_scanner.domain.fvg import FairValueGap
from htf_scanner.indicators.candle_features import calculate_candle_features


@dataclass(frozen=True)
class _FillMilestones:
    first_touch_at: datetime | None = None
    first_25_fill_at: datetime | None = None
    midpoint_fill_at: datetime | None = None
    first_75_fill_at: datetime | None = None
    full_fill_at: datetime | None = None
    invalidated_at: datetime | None = None
    expired_at: datetime | None = None


def detect_fvgs(
    candles: list[Candle],
    atr_period: int,
    config: FvgConfig,
) -> list[FairValueGap]:
    ordered = sorted(candles, key=lambda candle: candle.open_time)
    if any(not candle.is_closed for candle in ordered):
        raise ValueError("FVG detection only accepts closed candles")
    features = calculate_candle_features(ordered, atr_period)
    detected: list[FairValueGap] = []
    for index in range(2, len(ordered)):
        first, current = ordered[index - 2], ordered[index]
        side: FvgSide | None = None
        lower: Decimal | None = None
        upper: Decimal | None = None
        if current.high < first.low:
            side = FvgSide.BEARISH
            lower, upper = current.high, first.low
        elif current.low > first.high:
            side = FvgSide.BULLISH
            lower, upper = first.high, current.low
        if side is None or lower is None or upper is None:
            continue
        atr = float(features.iloc[index]["atr"])
        if not isfinite(atr) or atr <= 0:
            continue
        size = upper - lower
        size_atr = float(size) / atr
        if not config.minimum_size_atr <= size_atr <= config.maximum_size_atr:
            continue
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
        fvg = FairValueGap(
            id=uuid5(NAMESPACE_URL, identity),
            symbol=current.symbol,
            timeframe=current.timeframe,
            side=side,
            formed_at=current.open_time,
            known_at=current.close_time,
            lower=lower,
            upper=upper,
            midpoint=(lower + upper) / 2,
            size=size,
            size_atr=size_atr,
            source_candle_time=ordered[index - 1].open_time,
        )
        detected.append(_track_fill(fvg, ordered[index + 1 :], config.expire_after_d1_bars))
    return detected


def penetration_ratio(fvg: FairValueGap, candle: Candle) -> float:
    if fvg.side == FvgSide.BEARISH:
        penetration = (min(candle.high, fvg.upper) - fvg.lower) / fvg.size
    else:
        penetration = (fvg.upper - max(candle.low, fvg.lower)) / fvg.size
    return min(1.0, max(0.0, float(penetration)))


def _track_fill(
    fvg: FairValueGap,
    subsequent_candles: list[Candle],
    expire_after_bars: int,
) -> FairValueGap:
    maximum_fill = 0.0
    milestones = _FillMilestones()
    status = FvgStatus.ACTIVE
    for age, candle in enumerate(subsequent_candles, start=1):
        if age > expire_after_bars:
            status = FvgStatus.EXPIRED
            milestones = replace(milestones, expired_at=candle.close_time)
            break
        touched = candle.high >= fvg.lower and candle.low <= fvg.upper
        ratio = penetration_ratio(fvg, candle) if touched else 0.0
        maximum_fill = max(maximum_fill, ratio)
        if touched and milestones.first_touch_at is None:
            milestones = replace(milestones, first_touch_at=candle.close_time)
        if maximum_fill >= 0.25 and milestones.first_25_fill_at is None:
            milestones = replace(milestones, first_25_fill_at=candle.close_time)
        if maximum_fill >= 0.5 and milestones.midpoint_fill_at is None:
            milestones = replace(milestones, midpoint_fill_at=candle.close_time)
        if maximum_fill >= 0.75 and milestones.first_75_fill_at is None:
            milestones = replace(milestones, first_75_fill_at=candle.close_time)
        if maximum_fill >= 1.0 and milestones.full_fill_at is None:
            milestones = replace(milestones, full_fill_at=candle.close_time)
            status = FvgStatus.FULLY_FILLED
        invalidated = (fvg.side == FvgSide.BEARISH and candle.close > fvg.upper) or (
            fvg.side == FvgSide.BULLISH and candle.close < fvg.lower
        )
        if invalidated:
            status = FvgStatus.INVALIDATED
            milestones = replace(milestones, invalidated_at=candle.close_time)
            break
        if status == FvgStatus.FULLY_FILLED:
            break
        if maximum_fill > 0:
            status = FvgStatus.PARTIALLY_FILLED
    return fvg.model_copy(
        update={
            "fill_ratio": maximum_fill,
            "status": status,
            **milestones.__dict__,
        }
    )
