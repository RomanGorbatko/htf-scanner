from htf_scanner.config import LiquidityConfig
from htf_scanner.domain.candle import Candle
from htf_scanner.domain.enums import LiquidityInteractionType, SwingSide
from htf_scanner.domain.structure import MarketStructureSnapshot
from htf_scanner.domain.swing import SwingPoint
from htf_scanner.indicators.candle_features import calculate_candle_features
from htf_scanner.structure.liquidity_interactions import (
    LiquidityInteractionTracker,
    detect_liquidity_interactions,
)
from tests.conftest import make_candle
from tests.factories import make_swing


def _interaction_case() -> tuple[list[Candle], SwingPoint, list[MarketStructureSnapshot]]:
    candles = [
        make_candle(0, "9", "10", "8", "9"),
        make_candle(1, "9", "9.5", "8.5", "9"),
        make_candle(2, "9.8", "10.3", "9.5", "9.8"),
        make_candle(3, "9.9", "10.4", "9.8", "10.2"),
        make_candle(4, "10.2", "10.5", "10.1", "10.3"),
        make_candle(5, "10.2", "10.2", "9.4", "9.6"),
        make_candle(6, "9.5", "9.8", "9", "9.4"),
    ]
    reference = make_swing(candles, SwingSide.HIGH, "10", 0, 1)
    snapshots = [
        MarketStructureSnapshot(
            symbol=candles[0].symbol,
            timeframe="1d",
            known_at=candle.close_time,
            trend=None,
            active_leg=None,
            external_high_id=reference.id if index in range(1, 6) else None,
            external_high=reference.price if index in range(1, 6) else None,
        )
        for index, candle in enumerate(candles)
    ]
    return candles, reference, snapshots


def test_external_liquidity_interaction_lifecycle_is_causal() -> None:
    candles, reference, snapshots = _interaction_case()

    events = detect_liquidity_interactions(candles, [reference], snapshots, 1, LiquidityConfig())

    event_types = {event.event_type for event in events}
    assert event_types == set(LiquidityInteractionType)
    assert all(event.formed_at == event.candle_time for event in events)
    assert all(event.known_at > event.formed_at for event in events)
    assert all(event.reference_swing_id == reference.id for event in events)


def test_batch_and_incremental_liquidity_interactions_are_identical() -> None:
    candles, reference, snapshots = _interaction_case()
    config = LiquidityConfig()
    batch = detect_liquidity_interactions(candles, [reference], snapshots, 1, config)
    features = calculate_candle_features(candles, 1)
    tracker = LiquidityInteractionTracker(config)
    incremental = []
    for index, candle in enumerate(candles):
        before = [reference] if index > 1 and index <= 6 else []
        after = [reference] if index in range(1, 6) else []
        incremental.extend(
            tracker.update(candle, float(features.iloc[index]["atr"]), index, before, after)
        )

    assert incremental == batch
