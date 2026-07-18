from dataclasses import dataclass
from decimal import Decimal
from math import isfinite
from uuid import NAMESPACE_URL, uuid5

from htf_scanner.config import SwingConfig
from htf_scanner.domain.candle import Candle
from htf_scanner.domain.enums import Direction, SwingSide
from htf_scanner.domain.swing import SwingPoint
from htf_scanner.indicators.candle_features import calculate_candle_features


@dataclass(frozen=True)
class _Extreme:
    candle: Candle
    price: Decimal
    atr: float
    index: int


class CausalSwingDetector:
    """ATR-reversal ZigZag that confirms extremes only from closed current candles."""

    def __init__(self, config: SwingConfig) -> None:
        self._config = config
        self._direction: Direction | None = None
        self._candidate_high: _Extreme | None = None
        self._candidate_low: _Extreme | None = None
        self._next_index = 0

    def update(self, candle: Candle, atr: float) -> SwingPoint | None:
        index = self._next_index
        self._next_index += 1
        if not candle.is_closed:
            raise ValueError("swing detection only accepts closed candles")
        if not isfinite(atr) or atr <= 0:
            return None
        if self._candidate_high is None or self._candidate_low is None:
            self._candidate_high = _Extreme(candle, candle.high, atr, index)
            self._candidate_low = _Extreme(candle, candle.low, atr, index)
            return None

        if self._direction is None:
            self._update_both_extremes(candle, atr, index)
            return self._confirm_initial_direction(candle, atr, index)
        if self._direction == Direction.BULLISH:
            return self._track_high(candle, atr, index)
        return self._track_low(candle, atr, index)

    def export_state(self) -> dict[str, object]:
        return {
            "direction": self._direction.value if self._direction else None,
            "candidate_high": self._export_extreme(self._candidate_high),
            "candidate_low": self._export_extreme(self._candidate_low),
            "next_index": self._next_index,
        }

    def restore_state(self, payload: dict[str, object]) -> None:
        direction = payload.get("direction")
        self._direction = Direction(str(direction)) if direction is not None else None
        self._candidate_high = self._restore_extreme(payload.get("candidate_high"))
        self._candidate_low = self._restore_extreme(payload.get("candidate_low"))
        self._next_index = int(str(payload.get("next_index", 0)))

    @staticmethod
    def _export_extreme(extreme: _Extreme | None) -> dict[str, object] | None:
        if extreme is None:
            return None
        return {
            "candle": extreme.candle.model_dump(mode="json"),
            "price": str(extreme.price),
            "atr": extreme.atr,
            "index": extreme.index,
        }

    @staticmethod
    def _restore_extreme(payload: object) -> _Extreme | None:
        if payload is None:
            return None
        if not isinstance(payload, dict):
            raise ValueError("swing extreme state must be an object")
        return _Extreme(
            candle=Candle.model_validate(payload["candle"]),
            price=Decimal(str(payload["price"])),
            atr=float(payload["atr"]),
            index=int(payload["index"]),
        )

    def _update_both_extremes(self, candle: Candle, atr: float, index: int) -> None:
        if self._candidate_high is not None and candle.high >= self._candidate_high.price:
            self._candidate_high = _Extreme(candle, candle.high, atr, index)
        if self._candidate_low is not None and candle.low <= self._candidate_low.price:
            self._candidate_low = _Extreme(candle, candle.low, atr, index)

    def _confirm_initial_direction(
        self, candle: Candle, atr: float, index: int
    ) -> SwingPoint | None:
        assert self._candidate_high is not None and self._candidate_low is not None
        down_move = self._candidate_high.price - self._confirmation_low(candle)
        up_move = self._confirmation_high(candle) - self._candidate_low.price
        high_ready = self._is_confirmed(self._candidate_high, down_move, index)
        low_ready = self._is_confirmed(self._candidate_low, up_move, index)
        if high_ready and (
            not low_ready
            or float(down_move) / self._candidate_high.atr
            >= float(up_move) / self._candidate_low.atr
        ):
            swing = self._make_swing(SwingSide.HIGH, self._candidate_high, candle, down_move, index)
            self._direction = Direction.BEARISH
            self._candidate_low = _Extreme(candle, candle.low, atr, index)
            return swing
        if low_ready:
            swing = self._make_swing(SwingSide.LOW, self._candidate_low, candle, up_move, index)
            self._direction = Direction.BULLISH
            self._candidate_high = _Extreme(candle, candle.high, atr, index)
            return swing
        return None

    def _track_high(self, candle: Candle, atr: float, index: int) -> SwingPoint | None:
        assert self._candidate_high is not None
        if candle.high >= self._candidate_high.price:
            self._candidate_high = _Extreme(candle, candle.high, atr, index)
        move = self._candidate_high.price - self._confirmation_low(candle)
        if not self._is_confirmed(self._candidate_high, move, index):
            return None
        swing = self._make_swing(SwingSide.HIGH, self._candidate_high, candle, move, index)
        self._direction = Direction.BEARISH
        self._candidate_low = _Extreme(candle, candle.low, atr, index)
        return swing

    def _track_low(self, candle: Candle, atr: float, index: int) -> SwingPoint | None:
        assert self._candidate_low is not None
        if candle.low <= self._candidate_low.price:
            self._candidate_low = _Extreme(candle, candle.low, atr, index)
        move = self._confirmation_high(candle) - self._candidate_low.price
        if not self._is_confirmed(self._candidate_low, move, index):
            return None
        swing = self._make_swing(SwingSide.LOW, self._candidate_low, candle, move, index)
        self._direction = Direction.BULLISH
        self._candidate_high = _Extreme(candle, candle.high, atr, index)
        return swing

    def _is_confirmed(self, extreme: _Extreme, move: Decimal, index: int) -> bool:
        return (
            index - extreme.index >= self._config.minimum_bars_between_swings
            and float(move) >= self._config.reversal_atr * extreme.atr
        )

    def _confirmation_low(self, candle: Candle) -> Decimal:
        return candle.close if self._config.use_close_for_confirmation else candle.low

    def _confirmation_high(self, candle: Candle) -> Decimal:
        return candle.close if self._config.use_close_for_confirmation else candle.high

    @staticmethod
    def _make_swing(
        side: SwingSide,
        extreme: _Extreme,
        confirmation_candle: Candle,
        move: Decimal,
        confirmation_index: int,
    ) -> SwingPoint:
        identity = ":".join(
            [
                extreme.candle.symbol,
                extreme.candle.timeframe,
                side.value,
                extreme.candle.open_time.isoformat(),
                confirmation_candle.close_time.isoformat(),
                str(extreme.price),
            ]
        )
        return SwingPoint(
            id=uuid5(NAMESPACE_URL, identity),
            symbol=extreme.candle.symbol,
            timeframe=extreme.candle.timeframe,
            side=side,
            formed_at=extreme.candle.open_time,
            known_at=confirmation_candle.close_time,
            price=extreme.price,
            atr_at_formation=Decimal(str(extreme.atr)),
            confirmation_move_atr=float(move) / extreme.atr,
            bar_index=extreme.index,
            confirmation_bar_index=confirmation_index,
        )


def detect_causal_swings(
    candles: list[Candle], atr_period: int, config: SwingConfig
) -> list[SwingPoint]:
    ordered = sorted(candles, key=lambda item: item.open_time)
    features = calculate_candle_features(ordered, atr_period)
    detector = CausalSwingDetector(config)
    swings: list[SwingPoint] = []
    for index, candle in enumerate(ordered):
        swing = detector.update(candle, float(features.iloc[index]["atr"]))
        if swing is not None:
            swings.append(swing)
    return swings
