from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

import pytest

from htf_scanner.config import AppConfig, configuration_hash
from htf_scanner.detectors.d1_setup_detector import HTFSetupDetector
from htf_scanner.detectors.setup_state_machine import HTFSetupStateMachine
from htf_scanner.domain.candle import Candle
from htf_scanner.domain.displacement import Displacement
from htf_scanner.domain.enums import (
    Direction,
    FvgSide,
    FvgStatus,
    LiquidityContextType,
    SetupSide,
    SetupStatus,
    StructureBreakKind,
    StructureLevelType,
    SwingSide,
)
from htf_scanner.domain.fvg import FairValueGap
from htf_scanner.domain.liquidity import LiquidityContext
from htf_scanner.domain.structure import StructureBreak
from htf_scanner.domain.swing import SwingPoint
from tests.conftest import make_candle
from tests.factories import make_context, make_displacement, make_fvg, make_swing


def _setup_case(
    direction: Direction,
    classification: LiquidityContextType,
    *,
    structure_break: bool = True,
) -> tuple[
    list[Candle],
    FairValueGap,
    list[SwingPoint],
    StructureBreak,
    Displacement,
    LiquidityContext,
]:
    candles = [make_candle(index, "9", "11", "6", "9") for index in range(6)]
    attempt_side = SwingSide.HIGH if direction == Direction.BEARISH else SwingSide.LOW
    retracement_side = SwingSide.LOW if direction == Direction.BEARISH else SwingSide.HIGH
    external = make_swing(candles, attempt_side, "10", 1, 2)
    retracement = make_swing(candles, retracement_side, "8", 2, 3)
    attempt = make_swing(candles, attempt_side, "9.8", 3, 4)
    break_id = uuid5(NAMESPACE_URL, f"setup-break:{direction.value}")
    structure = StructureBreak(
        id=break_id,
        symbol=candles[0].symbol,
        timeframe="1d",
        direction=direction,
        kind=StructureBreakKind.MSS,
        level_type=StructureLevelType.INTERNAL,
        broken_swing_id=retracement.id,
        level_price=retracement.price,
        break_price=Decimal("7" if direction == Direction.BEARISH else "12"),
        formed_at=candles[5].open_time,
        known_at=candles[5].close_time,
        break_distance_atr=0.5,
        bar_index=5,
    )
    fvg = make_fvg(
        candles[5], FvgSide.BEARISH if direction == Direction.BEARISH else FvgSide.BULLISH
    )
    displacement = make_displacement(
        candles[5],
        direction,
        fvg,
        structure_break=structure_break,
        structure_break_id=break_id,
    )
    context = make_context(
        displacement,
        classification,
        3.0,
        external_reference_swing_id=external.id,
        attempt_swing_id=attempt.id,
        retracement_swing_id=retracement.id,
        structure_break_id=break_id,
    )
    return candles, fvg, [external, retracement, attempt], structure, displacement, context


@pytest.mark.parametrize(
    ("direction", "classification", "setup_side"),
    [
        (
            Direction.BEARISH,
            LiquidityContextType.SWEEP_AND_FAILED_CONTINUATION,
            SetupSide.SHORT,
        ),
        (
            Direction.BEARISH,
            LiquidityContextType.FAILED_CONTINUATION_HIGH,
            SetupSide.SHORT,
        ),
        (
            Direction.BULLISH,
            LiquidityContextType.FAILED_CONTINUATION_LOW,
            SetupSide.LONG,
        ),
    ],
)
def test_complete_causal_sequence_creates_active_setup(
    direction: Direction,
    classification: LiquidityContextType,
    setup_side: SetupSide,
) -> None:
    candles, fvg, swings, structure, displacement, context = _setup_case(direction, classification)
    config = AppConfig()

    setups, candidates, merged, transitions, rejected, events = HTFSetupDetector(
        config, configuration_hash(config)
    ).detect(candles, [fvg], swings, [structure], [displacement], [context])

    assert len(setups) == 1
    assert setups[0].side == setup_side
    assert setups[0].status == SetupStatus.ACTIVE
    assert setups[0].known_at == max(
        fvg.known_at, displacement.known_at, context.known_at, structure.known_at
    )
    assert setups[0].quality_score == sum(setups[0].score_components.values())
    assert [item.to_status for item in transitions] == [
        SetupStatus.CONFIRMED,
        SetupStatus.ACTIVE,
    ]
    assert rejected == []
    assert len(candidates) == 1 and candidates[0].canonical is True
    assert merged == []
    assert events[0].setup_id == setups[0].id


@pytest.mark.parametrize(
    "classification",
    [
        LiquidityContextType.ACCEPTED_BREAKOUT,
        LiquidityContextType.NO_CLEAR_CONTEXT,
        LiquidityContextType.UNSWEPT_EXTERNAL_LIQUIDITY,
    ],
)
def test_non_trigger_context_does_not_create_reversal_setup(
    classification: LiquidityContextType,
) -> None:
    candles, fvg, swings, structure, displacement, context = _setup_case(
        Direction.BEARISH, classification
    )

    setups, _, _, transitions, rejected, events = HTFSetupDetector(AppConfig(), "hash").detect(
        candles, [fvg], swings, [structure], [displacement], [context]
    )

    assert setups == []
    assert transitions == []
    assert events == []
    assert rejected and rejected[0].reasons == [f"blocked_context:{classification.value}"]


def test_displacement_and_fvg_without_structure_break_is_rejected() -> None:
    candles, fvg, swings, structure, displacement, context = _setup_case(
        Direction.BEARISH,
        LiquidityContextType.FAILED_CONTINUATION_HIGH,
        structure_break=False,
    )

    setups, _, _, _, rejected, _ = HTFSetupDetector(AppConfig(), "hash").detect(
        candles, [fvg], swings, [structure], [displacement], [context]
    )

    assert setups == []
    assert "missing_structure_break" in rejected[0].reasons


def test_components_from_different_impulses_cannot_be_combined() -> None:
    candles, fvg, swings, structure, displacement, context = _setup_case(
        Direction.BEARISH, LiquidityContextType.FAILED_CONTINUATION_HIGH
    )
    old_fvg = fvg.model_copy(
        update={
            "id": uuid5(NAMESPACE_URL, "old-fvg"),
            "formed_at": candles[0].open_time,
            "known_at": candles[0].close_time,
        }
    )
    displacement = displacement.model_copy(update={"fvg_id": old_fvg.id})

    setups, _, _, _, rejected, _ = HTFSetupDetector(AppConfig(), "hash").detect(
        candles, [old_fvg], swings, [structure], [displacement], [context]
    )

    assert setups == []
    assert "fvg_outside_displacement_sequence" in rejected[0].reasons


def test_overlapping_displacements_create_one_deterministic_canonical_setup() -> None:
    candles, fvg, swings, structure, first, first_context = _setup_case(
        Direction.BEARISH, LiquidityContextType.FAILED_CONTINUATION_HIGH
    )
    second = first.model_copy(
        update={
            "id": uuid5(NAMESPACE_URL, "overlapping-displacement"),
            "start_time": candles[4].open_time,
            "sequence_bars": 2,
            "score": first.score + 1,
        }
    )
    second_context = first_context.model_copy(
        update={
            "id": uuid5(NAMESPACE_URL, "overlapping-context"),
            "displacement_id": second.id,
        }
    )
    detector = HTFSetupDetector(AppConfig(), "hash")

    forward = detector.detect(
        candles,
        [fvg],
        swings,
        [structure],
        [first, second],
        [first_context, second_context],
    )
    reverse = detector.detect(
        candles,
        [fvg],
        swings,
        [structure],
        [second, first],
        [second_context, first_context],
    )

    setups, candidates, merged, _, rejected, _ = forward
    assert len(setups) == 1
    assert setups == reverse[0]
    assert next(item for item in candidates if item.canonical).displacement_id == second.id
    assert [item.id for item in candidates] == [item.id for item in reverse[1]]
    assert len(merged) == 1
    assert merged[0].reason == "MERGED_INTO_CANONICAL_CANDIDATE"
    assert rejected[0].reasons == ["MERGED_INTO_CANONICAL_CANDIDATE"]


def test_expiry_is_counted_by_processed_bar_index() -> None:
    candles, fvg, swings, structure, displacement, context = _setup_case(
        Direction.BEARISH, LiquidityContextType.FAILED_CONTINUATION_HIGH
    )
    config = AppConfig.model_validate({"d1_setup": {"max_setup_age_bars": 1}})
    active = HTFSetupDetector(config, "hash").detect(
        candles, [fvg], swings, [structure], [displacement], [context]
    )[0][0]
    candles.append(make_candle(6, "9", "10", "8", "9"))
    expired, _, _, transitions, _, _ = HTFSetupDetector(config, "hash").detect(
        candles, [fvg], swings, [structure], [displacement], [context]
    )

    assert active.status == SetupStatus.ACTIVE
    assert expired[0].status == SetupStatus.EXPIRED
    assert transitions[-1].to_status == SetupStatus.EXPIRED
    assert transitions[-1].bar_index == expired[0].expires_after_bar_index == 6


def test_fvg_invalidation_advances_active_setup_to_invalidated() -> None:
    candles, fvg, swings, structure, displacement, context = _setup_case(
        Direction.BEARISH, LiquidityContextType.FAILED_CONTINUATION_HIGH
    )
    invalidation_candle = make_candle(6, "9", "11", "8", "10")
    candles.append(invalidation_candle)
    invalidated_fvg = fvg.model_copy(
        update={
            "status": FvgStatus.INVALIDATED,
            "invalidated_at": invalidation_candle.close_time,
        }
    )

    setups, _, _, transitions, _, _ = HTFSetupDetector(AppConfig(), "hash").detect(
        candles,
        [invalidated_fvg],
        swings,
        [structure],
        [displacement],
        [context],
    )

    assert setups[0].status == SetupStatus.INVALIDATED
    assert transitions[-1].to_status == SetupStatus.INVALIDATED
    assert transitions[-1].reason == "fvg_invalidated"


def test_invalid_state_transition_is_rejected() -> None:
    candles, fvg, swings, structure, displacement, context = _setup_case(
        Direction.BEARISH, LiquidityContextType.FAILED_CONTINUATION_HIGH
    )
    setup = HTFSetupDetector(AppConfig(), "hash").detect(
        candles, [fvg], swings, [structure], [displacement], [context]
    )[0][0]
    candidate = setup.model_copy(update={"status": SetupStatus.CANDIDATE})

    with pytest.raises(ValueError, match="invalid setup transition"):
        HTFSetupStateMachine().transition(
            candidate, SetupStatus.ACTIVE, candidate.known_at, candidate.known_bar_index, "skip"
        )
