from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise

from htf_scanner.domain.candle import Candle


@dataclass(frozen=True)
class CandleQualityReport:
    ordered: list[Candle]
    diagnostics: list[str]


def inspect_candle_quality(candles: list[Candle], timeframe: str) -> CandleQualityReport:
    interval_seconds = {"1d": 86_400, "4h": 14_400}.get(timeframe)
    if interval_seconds is None:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    diagnostics: list[str] = []
    if any(left.open_time > right.open_time for left, right in pairwise(candles)):
        diagnostics.append("UNORDERED_CANDLES")
    counts: dict[datetime, int] = {}
    for candle in candles:
        counts[candle.open_time] = counts.get(candle.open_time, 0) + 1
        if candle.open_time.utcoffset() != timedelta(0):
            diagnostics.append(f"NON_UTC_TIMESTAMP:{candle.open_time.isoformat()}")
        if not candle.is_closed:
            diagnostics.append(f"INCOMPLETE_CANDLE:{candle.open_time.isoformat()}")
        if candle.timeframe != timeframe:
            diagnostics.append(f"TIMEFRAME_MISMATCH:{candle.open_time.isoformat()}")
    diagnostics.extend(
        f"DUPLICATE_CANDLE:{timestamp.isoformat()}"
        for timestamp, count in counts.items()
        if count > 1
    )
    unique = {candle.open_time: candle for candle in candles}
    ordered = sorted(unique.values(), key=lambda item: item.open_time)
    for previous, current in pairwise(ordered):
        if int((current.open_time - previous.open_time).total_seconds()) != interval_seconds:
            diagnostics.append(
                f"MISSING_INTERVAL:{previous.open_time.isoformat()}:{current.open_time.isoformat()}"
            )
    return CandleQualityReport(ordered=ordered, diagnostics=sorted(set(diagnostics)))
