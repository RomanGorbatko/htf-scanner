from datetime import datetime
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

from htf_scanner.config import StructureConfig
from htf_scanner.domain.candle import Candle
from htf_scanner.domain.enums import (
    Direction,
    StructureBreakKind,
    StructureLevelType,
    SwingSide,
)
from htf_scanner.domain.structure import (
    MarketStructureSnapshot,
    StructureBreak,
    StructurePromotion,
)
from htf_scanner.domain.swing import SwingPoint
from htf_scanner.indicators.candle_features import calculate_candle_features


class MarketStructureEngine:
    """Persistent causal internal/external structure hierarchy.

    The latest confirmed high and low are internal levels. External levels are persistent
    structural boundaries, never a rolling max/min. They are bootstrapped from the first
    confirmed swing of each side and remain active until a close breaks them or a causal
    promotion replaces them. A bearish close break of an internal low completes an upward
    continuation attempt and promotes the latest confirmed high to external/protected high;
    bullish logic is symmetric. An internal counter-trend break is MSS, an external
    counter-trend break is CHoCH, and a break with the active leg is BOS.
    """

    def __init__(self, config: StructureConfig) -> None:
        self._config = config
        self._swings: dict[UUID, SwingPoint] = {}
        self._internal_high: SwingPoint | None = None
        self._internal_low: SwingPoint | None = None
        self._external_high: SwingPoint | None = None
        self._external_low: SwingPoint | None = None
        self._protected_high: SwingPoint | None = None
        self._protected_low: SwingPoint | None = None
        self._broken: set[UUID] = set()
        self._active_leg: Direction | None = None
        self._next_index = 0

    def update(
        self,
        candle: Candle,
        atr: float,
        newly_confirmed: list[SwingPoint],
    ) -> tuple[list[StructureBreak], list[StructurePromotion], MarketStructureSnapshot]:
        bar_index = self._next_index
        self._next_index += 1
        self._add_swings(candle, newly_confirmed)
        previous_leg = self._active_leg
        candidates = self._break_candidates()
        breaks = [
            self._make_break(
                candle,
                atr,
                swing,
                level_type,
                direction,
                previous_leg,
                bar_index,
            )
            for swing, level_type, direction in candidates
            if swing.id not in self._broken and self._crossed(candle, swing, direction, atr)
        ]
        promotions: list[StructurePromotion] = []
        if breaks:
            direction = breaks[0].direction
            for structure_break in breaks:
                self._broken.add(structure_break.broken_swing_id)
                if (
                    direction == Direction.BULLISH
                    and self._external_high is not None
                    and structure_break.broken_swing_id == self._external_high.id
                ):
                    self._external_high = None
                if (
                    direction == Direction.BEARISH
                    and self._external_low is not None
                    and structure_break.broken_swing_id == self._external_low.id
                ):
                    self._external_low = None
            causal_break = next(
                (item for item in breaks if item.level_type == StructureLevelType.INTERNAL),
                breaks[0],
            )
            promotion = self._promote(candle, direction, causal_break)
            if promotion is not None:
                promotions.append(promotion)
            self._active_leg = direction
        return breaks, promotions, self.snapshot(candle)

    def _add_swings(self, candle: Candle, swings: list[SwingPoint]) -> None:
        for swing in swings:
            if swing.known_at > candle.close_time:
                raise ValueError("cannot add a swing before it is known")
            if swing.id in self._swings:
                continue
            self._swings[swing.id] = swing
            if swing.side == SwingSide.HIGH:
                self._internal_high = swing
                if self._external_high is None:
                    self._external_high = swing
            else:
                self._internal_low = swing
                if self._external_low is None:
                    self._external_low = swing

    def _break_candidates(
        self,
    ) -> list[tuple[SwingPoint, StructureLevelType, Direction]]:
        candidates: list[tuple[SwingPoint, StructureLevelType, Direction]] = []
        self._append_candidate(
            candidates, self._internal_high, self._external_high, Direction.BULLISH
        )
        self._append_candidate(
            candidates, self._internal_low, self._external_low, Direction.BEARISH
        )
        return candidates

    @staticmethod
    def _append_candidate(
        candidates: list[tuple[SwingPoint, StructureLevelType, Direction]],
        internal: SwingPoint | None,
        external: SwingPoint | None,
        direction: Direction,
    ) -> None:
        if internal is not None:
            level_type = (
                StructureLevelType.EXTERNAL
                if external is not None and internal.id == external.id
                else StructureLevelType.INTERNAL
            )
            candidates.append((internal, level_type, direction))
        if external is not None and (internal is None or external.id != internal.id):
            candidates.append((external, StructureLevelType.EXTERNAL, direction))

    def _make_break(
        self,
        candle: Candle,
        atr: float,
        level: SwingPoint,
        level_type: StructureLevelType,
        direction: Direction,
        previous_leg: Direction | None,
        bar_index: int,
    ) -> StructureBreak:
        if previous_leg is None or previous_leg == direction:
            kind = StructureBreakKind.BOS
        elif level_type == StructureLevelType.EXTERNAL:
            kind = StructureBreakKind.CHOCH
        else:
            kind = StructureBreakKind.MSS
        distance = abs(float(candle.close - level.price)) / atr if atr > 0 else 0.0
        identity = ":".join(
            [str(level.id), direction.value, candle.close_time.isoformat(), kind.value]
        )
        return StructureBreak(
            id=uuid5(NAMESPACE_URL, identity),
            symbol=candle.symbol,
            timeframe=candle.timeframe,
            direction=direction,
            kind=kind,
            level_type=level_type,
            broken_swing_id=level.id,
            level_price=level.price,
            break_price=candle.close,
            formed_at=candle.open_time,
            known_at=candle.close_time,
            break_distance_atr=distance,
            bar_index=bar_index,
        )

    def _promote(
        self, candle: Candle, direction: Direction, structure_break: StructureBreak
    ) -> StructurePromotion | None:
        promoted = self._internal_low if direction == Direction.BULLISH else self._internal_high
        if promoted is None:
            return None
        previous = self._external_low if direction == Direction.BULLISH else self._external_high
        if direction == Direction.BULLISH:
            self._protected_low = promoted
            self._external_low = promoted
        else:
            self._protected_high = promoted
            self._external_high = promoted
        if previous is not None and previous.id == promoted.id:
            return None
        identity = f"{structure_break.id}:promote:{promoted.id}"
        return StructurePromotion(
            id=uuid5(NAMESPACE_URL, identity),
            symbol=candle.symbol,
            timeframe=candle.timeframe,
            direction=direction,
            promoted_swing_id=promoted.id,
            replaced_external_swing_id=previous.id if previous else None,
            protected_swing_id=promoted.id,
            caused_by_break_id=structure_break.id,
            promoted_at=candle.close_time,
            bar_index=structure_break.bar_index,
        )

    def snapshot(self, candle: Candle) -> MarketStructureSnapshot:
        return MarketStructureSnapshot(
            symbol=candle.symbol,
            timeframe=candle.timeframe,
            known_at=candle.close_time,
            trend=self._active_leg,
            active_leg=self._active_leg,
            internal_high_id=self._internal_high.id if self._internal_high else None,
            internal_low_id=self._internal_low.id if self._internal_low else None,
            external_high_id=self._external_high.id if self._external_high else None,
            external_low_id=self._external_low.id if self._external_low else None,
            internal_high=self._internal_high.price if self._internal_high else None,
            internal_low=self._internal_low.price if self._internal_low else None,
            external_high=self._external_high.price if self._external_high else None,
            external_low=self._external_low.price if self._external_low else None,
            protected_high_id=self._protected_high.id if self._protected_high else None,
            protected_low_id=self._protected_low.id if self._protected_low else None,
            protected_high=self._protected_high.price if self._protected_high else None,
            protected_low=self._protected_low.price if self._protected_low else None,
        )

    def export_state(self) -> dict[str, object]:
        return {
            "swings": [item.model_dump(mode="json") for item in self._swings.values()],
            "internal_high": self._id(self._internal_high),
            "internal_low": self._id(self._internal_low),
            "external_high": self._id(self._external_high),
            "external_low": self._id(self._external_low),
            "protected_high": self._id(self._protected_high),
            "protected_low": self._id(self._protected_low),
            "broken": [str(item) for item in sorted(self._broken, key=str)],
            "active_leg": self._active_leg.value if self._active_leg else None,
            "next_index": self._next_index,
        }

    def restore_state(self, payload: dict[str, object]) -> None:
        raw_swings = payload.get("swings", [])
        if not isinstance(raw_swings, list):
            raise ValueError("structure swings state must be a list")
        self._swings = {
            swing.id: swing for swing in (SwingPoint.model_validate(item) for item in raw_swings)
        }
        self._internal_high = self._by_id(payload.get("internal_high"))
        self._internal_low = self._by_id(payload.get("internal_low"))
        self._external_high = self._by_id(payload.get("external_high"))
        self._external_low = self._by_id(payload.get("external_low"))
        self._protected_high = self._by_id(payload.get("protected_high"))
        self._protected_low = self._by_id(payload.get("protected_low"))
        broken = payload.get("broken", [])
        if not isinstance(broken, list):
            raise ValueError("structure broken state must be a list")
        self._broken = {UUID(str(item)) for item in broken}
        leg = payload.get("active_leg")
        self._active_leg = Direction(str(leg)) if leg is not None else None
        self._next_index = int(str(payload.get("next_index", 0)))

    @staticmethod
    def _id(swing: SwingPoint | None) -> str | None:
        return str(swing.id) if swing else None

    def _by_id(self, value: object) -> SwingPoint | None:
        return self._swings.get(UUID(str(value))) if value is not None else None

    def _crossed(self, candle: Candle, level: SwingPoint, direction: Direction, atr: float) -> bool:
        buffer = (
            Decimal(str(self._config.minimum_break_atr * atr))
            if self._config.break_mode == "close_plus_buffer"
            else Decimal("0")
        )
        if direction == Direction.BULLISH:
            return candle.close > level.price + buffer
        return candle.close < level.price - buffer


def detect_market_structure(
    candles: list[Candle],
    swings: list[SwingPoint],
    atr_period: int,
    config: StructureConfig,
) -> tuple[
    list[StructureBreak],
    list[StructurePromotion],
    list[MarketStructureSnapshot],
]:
    ordered = sorted(candles, key=lambda item: item.open_time)
    features = calculate_candle_features(ordered, atr_period)
    swings_by_known_at: dict[datetime, list[SwingPoint]] = {}
    for swing in swings:
        swings_by_known_at.setdefault(swing.known_at, []).append(swing)
    engine = MarketStructureEngine(config)
    all_breaks: list[StructureBreak] = []
    all_promotions: list[StructurePromotion] = []
    snapshots: list[MarketStructureSnapshot] = []
    for index, candle in enumerate(ordered):
        breaks, promotions, snapshot = engine.update(
            candle,
            float(features.iloc[index]["atr"]),
            swings_by_known_at.get(candle.close_time, []),
        )
        all_breaks.extend(breaks)
        all_promotions.extend(promotions)
        snapshots.append(snapshot)
    return all_breaks, all_promotions, snapshots
