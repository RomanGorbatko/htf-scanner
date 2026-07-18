from htf_scanner.config import StructureConfig, SwingConfig
from htf_scanner.domain.candle import Candle
from htf_scanner.domain.enums import Direction, StructureBreakKind, StructureLevelType, SwingSide
from htf_scanner.domain.swing import SwingPoint
from htf_scanner.indicators.candle_features import calculate_candle_features
from htf_scanner.structure.causal_swings import detect_causal_swings
from htf_scanner.structure.market_structure import (
    MarketStructureEngine,
    detect_market_structure,
)
from tests.conftest import make_candle
from tests.factories import make_swing
from tests.unit.test_causal_swings import swing_candles


def _hierarchy_case() -> tuple[list[Candle], list[SwingPoint]]:
    candles = [
        make_candle(0, "10", "20", "9", "10"),
        make_candle(1, "10", "11", "4", "10"),
        make_candle(2, "10", "18", "9", "10"),
        make_candle(3, "10", "12", "8", "10"),
        make_candle(4, "10", "19", "9", "10"),
        make_candle(5, "10", "12", "9", "10"),
        make_candle(6, "10", "11", "6", "7"),
    ]
    swings = [
        make_swing(candles, SwingSide.HIGH, "20", 0, 1),
        make_swing(candles, SwingSide.LOW, "4", 1, 2),
        make_swing(candles, SwingSide.HIGH, "18", 2, 3),
        make_swing(candles, SwingSide.LOW, "8", 3, 4),
        make_swing(candles, SwingSide.HIGH, "19", 4, 5),
    ]
    return candles, swings


def test_market_structure_classifies_bos_then_choch_by_close() -> None:
    candles = swing_candles()
    swings = detect_causal_swings(
        candles, 2, SwingConfig(reversal_atr=0.5, minimum_bars_between_swings=1)
    )

    breaks, promotions, snapshots = detect_market_structure(
        candles, swings, 2, StructureConfig(break_mode="close", minimum_break_atr=0)
    )

    assert [(item.direction, item.kind) for item in breaks] == [
        (Direction.BULLISH, StructureBreakKind.BOS),
        (Direction.BEARISH, StructureBreakKind.CHOCH),
    ]
    assert promotions == []
    assert snapshots[-1].trend == Direction.BEARISH
    assert breaks[0].known_at == candles[5].close_time
    assert breaks[1].known_at == candles[7].close_time


def test_major_external_high_persists_after_multiple_internal_highs() -> None:
    candles, swings = _hierarchy_case()
    _, _, snapshots = detect_market_structure(
        candles[:6], swings, 1, StructureConfig(break_mode="close", minimum_break_atr=0)
    )

    assert snapshots[3].internal_high == 18
    assert snapshots[5].internal_high == 19
    assert snapshots[3].external_high == 20
    assert snapshots[5].external_high == 20


def test_internal_swing_is_promoted_after_relevant_structure_break() -> None:
    candles, swings = _hierarchy_case()

    breaks, promotions, snapshots = detect_market_structure(
        candles, swings, 1, StructureConfig(break_mode="close", minimum_break_atr=0)
    )

    internal_break = next(
        item
        for item in breaks
        if item.level_type == StructureLevelType.INTERNAL and item.direction == Direction.BEARISH
    )
    assert internal_break.broken_swing_id == swings[3].id
    assert len(promotions) == 1
    assert promotions[0].caused_by_break_id == internal_break.id
    assert promotions[0].promoted_swing_id == swings[4].id
    assert promotions[0].replaced_external_swing_id == swings[0].id
    assert snapshots[-1].external_high_id == swings[4].id
    assert snapshots[-1].protected_high_id == swings[4].id


def test_batch_and_incremental_structure_hierarchy_are_identical() -> None:
    candles, swings = _hierarchy_case()
    config = StructureConfig(break_mode="close", minimum_break_atr=0)
    batch_breaks, batch_promotions, batch_snapshots = detect_market_structure(
        candles, swings, 1, config
    )
    features = calculate_candle_features(candles, 1)
    engine = MarketStructureEngine(config)
    incremental_breaks = []
    incremental_promotions = []
    incremental_snapshots = []
    for index, candle in enumerate(candles):
        newly_known = [swing for swing in swings if swing.known_at == candle.close_time]
        breaks, promotions, snapshot = engine.update(
            candle, float(features.iloc[index]["atr"]), newly_known
        )
        incremental_breaks.extend(breaks)
        incremental_promotions.extend(promotions)
        incremental_snapshots.append(snapshot)

    assert incremental_breaks == batch_breaks
    assert incremental_promotions == batch_promotions
    assert incremental_snapshots == batch_snapshots
