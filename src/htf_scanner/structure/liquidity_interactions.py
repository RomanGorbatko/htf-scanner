from dataclasses import dataclass
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

from htf_scanner.config import LiquidityConfig
from htf_scanner.domain.candle import Candle
from htf_scanner.domain.enums import Direction, LiquidityInteractionType, SwingSide
from htf_scanner.domain.liquidity import LiquidityInteraction
from htf_scanner.domain.structure import MarketStructureSnapshot
from htf_scanner.domain.swing import SwingPoint
from htf_scanner.indicators.candle_features import calculate_candle_features


@dataclass
class _LevelState:
    touched: bool = False
    consecutive_closes_beyond: int = 0
    maximum_acceptance_distance_atr: float = 0.0
    beyond_active: bool = False
    accepted_active: bool = False


class LiquidityInteractionTracker:
    """Track causal price interactions without mutating structural external levels."""

    def __init__(self, config: LiquidityConfig) -> None:
        self._config = config
        self._states: dict[UUID, _LevelState] = {}

    def update(
        self,
        candle: Candle,
        atr: float,
        bar_index: int,
        active_before: list[SwingPoint],
        active_after: list[SwingPoint],
    ) -> list[LiquidityInteraction]:
        if atr <= 0:
            return []
        events: list[LiquidityInteraction] = []
        after_ids = {swing.id for swing in active_after}
        for reference in active_before:
            level_id = external_level_id(reference.id)
            state = self._states.setdefault(level_id, _LevelState())
            touched = self._touched(candle, reference)
            excursion_price = self._excursion(candle, reference)
            excursion_atr = float(excursion_price) / atr
            close_beyond = self._close_beyond(candle, reference)
            if close_beyond:
                state.consecutive_closes_beyond += 1
                state.beyond_active = True
            else:
                state.consecutive_closes_beyond = 0
            state.maximum_acceptance_distance_atr = max(
                state.maximum_acceptance_distance_atr, excursion_atr
            )
            if touched and not state.touched:
                events.append(
                    self._event(
                        candle,
                        reference,
                        LiquidityInteractionType.TOUCHED,
                        bar_index,
                        state,
                        excursion_price,
                        excursion_atr,
                    )
                )
                state.touched = True
            accepted_now = (
                state.consecutive_closes_beyond >= self._config.accepted_breakout_min_closes
                and state.maximum_acceptance_distance_atr >= self._config.accepted_breakout_min_atr
            )
            swept = (
                touched
                and not close_beyond
                and self._config.minimum_sweep_atr
                <= excursion_atr
                <= self._config.maximum_sweep_atr
                and not state.accepted_active
            )
            if swept:
                events.append(
                    self._event(
                        candle,
                        reference,
                        LiquidityInteractionType.SWEPT,
                        bar_index,
                        state,
                        excursion_price,
                        excursion_atr,
                    )
                )
            if touched and not close_beyond and not state.accepted_active:
                events.append(
                    self._event(
                        candle,
                        reference,
                        LiquidityInteractionType.REJECTED,
                        bar_index,
                        state,
                        excursion_price,
                        excursion_atr,
                    )
                )
            if accepted_now and not state.accepted_active:
                events.append(
                    self._event(
                        candle,
                        reference,
                        LiquidityInteractionType.ACCEPTED_BEYOND,
                        bar_index,
                        state,
                        excursion_price,
                        excursion_atr,
                    )
                )
                state.accepted_active = True
            if not close_beyond and state.beyond_active:
                events.append(
                    self._event(
                        candle,
                        reference,
                        LiquidityInteractionType.RECLAIMED,
                        bar_index,
                        state,
                        excursion_price,
                        excursion_atr,
                    )
                )
                state.beyond_active = False
                state.accepted_active = False
            if reference.id not in after_ids:
                events.append(
                    self._event(
                        candle,
                        reference,
                        LiquidityInteractionType.INVALIDATED,
                        bar_index,
                        state,
                        excursion_price,
                        excursion_atr,
                    )
                )
        return events

    def export_state(self) -> dict[str, object]:
        return {
            str(level_id): {
                "touched": state.touched,
                "consecutive_closes_beyond": state.consecutive_closes_beyond,
                "maximum_acceptance_distance_atr": state.maximum_acceptance_distance_atr,
                "beyond_active": state.beyond_active,
                "accepted_active": state.accepted_active,
            }
            for level_id, state in self._states.items()
        }

    def restore_state(self, payload: dict[str, object]) -> None:
        states: dict[UUID, _LevelState] = {}
        for level_id, raw in payload.items():
            if not isinstance(raw, dict):
                raise ValueError("liquidity level state must be an object")
            states[UUID(level_id)] = _LevelState(
                touched=bool(raw.get("touched", False)),
                consecutive_closes_beyond=int(raw.get("consecutive_closes_beyond", 0)),
                maximum_acceptance_distance_atr=float(
                    raw.get("maximum_acceptance_distance_atr", 0.0)
                ),
                beyond_active=bool(raw.get("beyond_active", False)),
                accepted_active=bool(raw.get("accepted_active", False)),
            )
        self._states = states

    @staticmethod
    def _event(
        candle: Candle,
        reference: SwingPoint,
        event_type: LiquidityInteractionType,
        bar_index: int,
        state: _LevelState,
        excursion_price: Decimal,
        excursion_atr: float,
    ) -> LiquidityInteraction:
        level_id = external_level_id(reference.id)
        identity = f"{level_id}:{event_type.value}:{candle.open_time.isoformat()}"
        return LiquidityInteraction(
            id=uuid5(NAMESPACE_URL, identity),
            external_level_id=level_id,
            reference_swing_id=reference.id,
            symbol=candle.symbol,
            timeframe=candle.timeframe,
            direction=(
                Direction.BEARISH if reference.side == SwingSide.HIGH else Direction.BULLISH
            ),
            event_type=event_type,
            level_price=reference.price,
            formed_at=candle.open_time,
            known_at=candle.close_time,
            candle_time=candle.open_time,
            bar_index=bar_index,
            excursion_price=excursion_price,
            excursion_atr=excursion_atr,
            close_relative_to_level=candle.close - reference.price,
            closes_beyond_level=state.consecutive_closes_beyond,
            maximum_acceptance_distance_atr=state.maximum_acceptance_distance_atr,
        )

    @staticmethod
    def _touched(candle: Candle, reference: SwingPoint) -> bool:
        if reference.side == SwingSide.HIGH:
            return candle.high >= reference.price
        return candle.low <= reference.price

    @staticmethod
    def _close_beyond(candle: Candle, reference: SwingPoint) -> bool:
        if reference.side == SwingSide.HIGH:
            return candle.close > reference.price
        return candle.close < reference.price

    @staticmethod
    def _excursion(candle: Candle, reference: SwingPoint) -> Decimal:
        if reference.side == SwingSide.HIGH:
            return max(Decimal("0"), candle.high - reference.price)
        return max(Decimal("0"), reference.price - candle.low)


def external_level_id(reference_swing_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"external-liquidity-level:{reference_swing_id}")


def detect_liquidity_interactions(
    candles: list[Candle],
    swings: list[SwingPoint],
    snapshots: list[MarketStructureSnapshot],
    atr_period: int,
    config: LiquidityConfig,
) -> list[LiquidityInteraction]:
    ordered = sorted(candles, key=lambda item: item.open_time)
    if len(ordered) != len(snapshots):
        raise ValueError("one market-structure snapshot is required per candle")
    features = calculate_candle_features(ordered, atr_period)
    swings_by_id = {swing.id: swing for swing in swings}
    tracker = LiquidityInteractionTracker(config)
    events: list[LiquidityInteraction] = []
    for index, candle in enumerate(ordered):
        before = snapshots[index - 1] if index > 0 else None
        after = snapshots[index]
        events.extend(
            tracker.update(
                candle,
                float(features.iloc[index]["atr"]),
                index,
                _external_swings(before, swings_by_id),
                _external_swings(after, swings_by_id),
            )
        )
    return events


def _external_swings(
    snapshot: MarketStructureSnapshot | None,
    swings_by_id: dict[UUID, SwingPoint],
) -> list[SwingPoint]:
    if snapshot is None:
        return []
    return [
        swings_by_id[swing_id]
        for swing_id in (snapshot.external_high_id, snapshot.external_low_id)
        if swing_id is not None
    ]
