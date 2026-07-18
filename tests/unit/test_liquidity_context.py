from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

import pytest

from htf_scanner.config import LiquidityConfig
from htf_scanner.domain.candle import Candle
from htf_scanner.domain.displacement import Displacement
from htf_scanner.domain.enums import (
    Direction,
    FvgSide,
    LiquidityContextType,
    LiquidityInteractionType,
    StructureBreakKind,
    StructureLevelType,
    SwingSide,
)
from htf_scanner.domain.liquidity import LiquidityInteraction
from htf_scanner.domain.structure import (
    MarketStructureSnapshot,
    StructureBreak,
    StructurePromotion,
)
from htf_scanner.structure.liquidity_context import (
    ContinuationStructureContext,
    LiquidityContextClassifier,
)
from htf_scanner.structure.liquidity_interactions import external_level_id
from tests.conftest import make_candle
from tests.factories import make_displacement, make_fvg, make_swing


def _case(
    direction: Direction,
    *,
    attempt_price: str,
    retracement_price: str | None = None,
    accepted: bool = False,
) -> tuple[list[Candle], Displacement, ContinuationStructureContext]:
    if direction == Direction.BEARISH:
        candles = [
            make_candle(0, "8", "9", "7", "8"),
            make_candle(1, "9", "10", "8", "9"),
            make_candle(2, "9", "9.5", "6", "8"),
            make_candle(3, "9.5", attempt_price, "9", "10.3" if accepted else "9.8"),
            make_candle(4, "10.3", "10.8", "10.1", "10.5")
            if accepted
            else make_candle(4, "9.7", "9.9", "8.8", "9.2"),
            make_candle(5, "9.2", "9.3", "5", "5.5"),
        ]
        attempt_side, retracement_side = SwingSide.HIGH, SwingSide.LOW
        reference_price = "10"
        retracement_price = retracement_price or "6"
    else:
        candles = [
            make_candle(0, "12", "13", "11", "12"),
            make_candle(1, "10", "12", "8", "9"),
            make_candle(2, "9", "14", "8.5", "12"),
            make_candle(3, "8.5", "9", attempt_price, "7.7" if accepted else "8.2"),
            make_candle(4, "7.7", "7.9", "7.2", "7.5")
            if accepted
            else make_candle(4, "8.2", "9.2", "8.1", "8.8"),
            make_candle(5, "8.8", "14", "8.7", "13.5"),
        ]
        attempt_side, retracement_side = SwingSide.LOW, SwingSide.HIGH
        reference_price = "8"
        retracement_price = retracement_price or "14"
    external = make_swing(candles, attempt_side, reference_price, 1, 2)
    retracement = make_swing(candles, retracement_side, retracement_price, 2, 3)
    attempt = make_swing(candles, attempt_side, attempt_price, 3, 4)
    break_id = uuid5(NAMESPACE_URL, f"liquidity-break:{direction}:{attempt_price}:{accepted}")
    structure_break = StructureBreak(
        id=break_id,
        symbol=candles[0].symbol,
        timeframe="1d",
        direction=direction,
        kind=StructureBreakKind.MSS,
        level_type=StructureLevelType.INTERNAL,
        broken_swing_id=retracement.id,
        level_price=retracement.price,
        break_price=candles[5].close,
        formed_at=candles[5].open_time,
        known_at=candles[5].close_time,
        break_distance_atr=0.5,
        bar_index=5,
    )
    fvg = make_fvg(
        candles[5], FvgSide.BEARISH if direction == Direction.BEARISH else FvgSide.BULLISH
    )
    displacement = make_displacement(
        candles[5], direction, fvg, structure_break_id=structure_break.id
    )
    promotion = StructurePromotion(
        id=uuid5(NAMESPACE_URL, f"promotion:{break_id}"),
        symbol=candles[0].symbol,
        timeframe="1d",
        direction=direction,
        promoted_swing_id=attempt.id,
        replaced_external_swing_id=external.id,
        protected_swing_id=attempt.id,
        caused_by_break_id=structure_break.id,
        promoted_at=candles[5].close_time,
        bar_index=5,
    )
    snapshot = MarketStructureSnapshot(
        symbol=candles[0].symbol,
        timeframe="1d",
        known_at=candles[4].close_time,
        trend=None,
        active_leg=None,
        internal_high_id=attempt.id if attempt_side == SwingSide.HIGH else retracement.id,
        internal_low_id=attempt.id if attempt_side == SwingSide.LOW else retracement.id,
        external_high_id=external.id if attempt_side == SwingSide.HIGH else None,
        external_low_id=external.id if attempt_side == SwingSide.LOW else None,
    )
    structure = ContinuationStructureContext(
        external_reference=external,
        retracement=retracement,
        continuation_attempt=attempt,
        structure_state=snapshot,
        structure_break=structure_break,
        promotion=promotion,
    )
    return candles, displacement, structure


def _sweep_interaction(
    candles: list[Candle], structure: ContinuationStructureContext
) -> LiquidityInteraction:
    reference = structure.external_reference
    candle = candles[structure.continuation_attempt.bar_index]
    excursion = abs(structure.continuation_attempt.price - reference.price)
    return LiquidityInteraction(
        id=uuid5(NAMESPACE_URL, f"test-sweep:{reference.id}:{candle.open_time}"),
        external_level_id=external_level_id(reference.id),
        reference_swing_id=reference.id,
        symbol=candle.symbol,
        timeframe=candle.timeframe,
        direction=structure.structure_break.direction,
        event_type=LiquidityInteractionType.SWEPT,
        level_price=reference.price,
        formed_at=candle.open_time,
        known_at=candle.close_time,
        candle_time=candle.open_time,
        bar_index=structure.continuation_attempt.bar_index,
        excursion_price=excursion,
        excursion_atr=0.1,
        close_relative_to_level=candle.close - reference.price,
        closes_beyond_level=0,
        maximum_acceptance_distance_atr=0.1,
    )


@pytest.mark.parametrize(
    ("direction", "attempt_price", "expected"),
    [
        (Direction.BEARISH, "9.8", LiquidityContextType.FAILED_CONTINUATION_HIGH),
        (Direction.BULLISH, "8.2", LiquidityContextType.FAILED_CONTINUATION_LOW),
    ],
)
def test_failed_continuation_without_sweep_is_symmetric(
    direction: Direction, attempt_price: str, expected: LiquidityContextType
) -> None:
    candles, displacement, structure = _case(direction, attempt_price=attempt_price)

    context = LiquidityContextClassifier(candles, 1, LiquidityConfig()).classify(
        displacement, structure
    )

    assert context.classification == expected
    assert context.external_liquidity_remained is True
    assert context.failed_hard_gates == []
    assert context.retracement_swing_id == structure.retracement.id
    assert context.structure_break_id == structure.structure_break.id


@pytest.mark.parametrize(
    ("direction", "attempt_price"),
    [(Direction.BEARISH, "10.4"), (Direction.BULLISH, "7.6")],
)
def test_liquidity_sweep_with_reversal_is_symmetric(
    direction: Direction, attempt_price: str
) -> None:
    candles, displacement, structure = _case(direction, attempt_price=attempt_price)

    interaction = _sweep_interaction(candles, structure)
    context = LiquidityContextClassifier(candles, 1, LiquidityConfig(), [interaction]).classify(
        displacement, structure
    )

    assert context.classification == LiquidityContextType.SWEEP_AND_FAILED_CONTINUATION
    assert context.sweep is True
    assert context.accepted_breakout is False


def test_prior_sweep_then_retracement_and_later_weak_attempt_is_combined() -> None:
    candles = [
        make_candle(0, "8", "9", "7", "8"),
        make_candle(1, "9", "10", "8", "9"),
        make_candle(2, "9", "9.5", "8", "9"),
        make_candle(3, "9.8", "10.3", "9.5", "9.7"),
        make_candle(4, "9", "9.2", "6", "7"),
        make_candle(5, "7", "8", "6.5", "7.5"),
        make_candle(6, "8", "9.7", "7.8", "9.2"),
        make_candle(7, "9", "9.3", "8.5", "8.8"),
        make_candle(8, "8.7", "8.8", "5", "5.5"),
    ]
    external = make_swing(candles, SwingSide.HIGH, "10", 1, 2)
    retracement = make_swing(candles, SwingSide.LOW, "6", 4, 5)
    attempt = make_swing(candles, SwingSide.HIGH, "9.7", 6, 7)
    break_id = uuid5(NAMESPACE_URL, "multi-stage-break")
    structure_break = StructureBreak(
        id=break_id,
        symbol=candles[0].symbol,
        timeframe="1d",
        direction=Direction.BEARISH,
        kind=StructureBreakKind.MSS,
        level_type=StructureLevelType.INTERNAL,
        broken_swing_id=retracement.id,
        level_price=retracement.price,
        break_price=candles[8].close,
        formed_at=candles[8].open_time,
        known_at=candles[8].close_time,
        break_distance_atr=0.5,
        bar_index=8,
    )
    promotion = StructurePromotion(
        id=uuid5(NAMESPACE_URL, "multi-stage-promotion"),
        symbol=candles[0].symbol,
        timeframe="1d",
        direction=Direction.BEARISH,
        promoted_swing_id=attempt.id,
        replaced_external_swing_id=external.id,
        protected_swing_id=attempt.id,
        caused_by_break_id=break_id,
        promoted_at=candles[8].close_time,
        bar_index=8,
    )
    snapshot = MarketStructureSnapshot(
        symbol=candles[0].symbol,
        timeframe="1d",
        known_at=candles[7].close_time,
        trend=Direction.BULLISH,
        active_leg=Direction.BULLISH,
        internal_high_id=attempt.id,
        internal_low_id=retracement.id,
        external_high_id=external.id,
    )
    structure = ContinuationStructureContext(
        external_reference=external,
        retracement=retracement,
        continuation_attempt=attempt,
        structure_state=snapshot,
        structure_break=structure_break,
        promotion=promotion,
    )
    fvg = make_fvg(candles[8], FvgSide.BEARISH)
    displacement = make_displacement(
        candles[8], Direction.BEARISH, fvg, structure_break_id=break_id
    )
    sweep = LiquidityInteraction(
        id=uuid5(NAMESPACE_URL, "multi-stage-sweep"),
        external_level_id=external_level_id(external.id),
        reference_swing_id=external.id,
        symbol=candles[0].symbol,
        timeframe="1d",
        direction=Direction.BEARISH,
        event_type=LiquidityInteractionType.SWEPT,
        level_price=external.price,
        formed_at=candles[3].open_time,
        known_at=candles[3].close_time,
        candle_time=candles[3].open_time,
        bar_index=3,
        excursion_price=Decimal("0.3"),
        excursion_atr=0.1,
        close_relative_to_level=Decimal("-0.3"),
        closes_beyond_level=0,
        maximum_acceptance_distance_atr=0.1,
    )

    context, sequence = LiquidityContextClassifier(
        candles, 1, LiquidityConfig(), [sweep]
    ).classify_with_sequence(displacement, structure)

    assert context.classification == LiquidityContextType.SWEEP_AND_FAILED_CONTINUATION
    assert sequence.sweep_interaction_id == sweep.id
    assert sequence.interaction_ids == [sweep.id]
    assert sequence.failed_hard_gates == []


def test_accepted_breakout_uses_local_attempt_window() -> None:
    candles, displacement, structure = _case(Direction.BEARISH, attempt_price="11.2", accepted=True)

    context = LiquidityContextClassifier(candles, 1, LiquidityConfig()).classify(
        displacement, structure
    )

    assert context.classification == LiquidityContextType.ACCEPTED_BREAKOUT
    assert context.accepted_breakout is True
    assert context.features["closes_beyond_external"] == 2
    assert context.score == 0


def test_retracement_depth_is_a_soft_quality_feature() -> None:
    candles, displacement, structure = _case(
        Direction.BEARISH, attempt_price="9.9", retracement_price="9.8"
    )

    context = LiquidityContextClassifier(candles, 1, LiquidityConfig()).classify(
        displacement, structure
    )

    assert context.classification == LiquidityContextType.FAILED_CONTINUATION_HIGH
    retracement_size = context.features["retracement_size_atr"]
    assert isinstance(retracement_size, float)
    assert retracement_size < LiquidityConfig().minimum_retracement_atr


@pytest.mark.parametrize(
    "config",
    [
        LiquidityConfig(failed_continuation_max_distance_atr=0.01),
        LiquidityConfig(failed_continuation_followup_bars=1),
    ],
)
def test_distance_and_timing_thresholds_are_soft_penalties(config: LiquidityConfig) -> None:
    candles, displacement, structure = _case(Direction.BEARISH, attempt_price="9.8")

    context = LiquidityContextClassifier(candles, 1, config).classify(displacement, structure)

    assert context.classification == LiquidityContextType.FAILED_CONTINUATION_HIGH
    assert context.failed_hard_gates == []
    assert any(value < 0 for value in context.score_penalties.values())


def test_missing_explicit_structure_is_no_clear_context() -> None:
    candles, displacement, _ = _case(Direction.BEARISH, attempt_price="9.8")

    context = LiquidityContextClassifier(candles, 1, LiquidityConfig()).classify(displacement, None)

    assert context.classification == LiquidityContextType.NO_CLEAR_CONTEXT
    assert context.failed_hard_gates
