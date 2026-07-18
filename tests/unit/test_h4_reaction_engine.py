from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import pytest

from htf_scanner.config import AppConfig
from htf_scanner.data.validation import inspect_candle_quality
from htf_scanner.detectors.h4_reaction_detector import H4ReactionEngine, detect_h4_reactions
from htf_scanner.detectors.h4_reaction_state_machine import H4ReactionStateMachine
from htf_scanner.domain.candle import Candle
from htf_scanner.domain.displacement import Displacement
from htf_scanner.domain.enums import (
    Direction,
    FvgSide,
    H4ReactionStatus,
    H4TouchType,
    LiquidityContextType,
    SetupSide,
    StructureBreakKind,
    StructureLevelType,
)
from htf_scanner.domain.fvg import FairValueGap
from htf_scanner.domain.setup import HTFSetup
from htf_scanner.domain.structure import StructureBreak

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def h4(index: int, open_: str, high: str, low: str, close: str, *, closed: bool = True) -> Candle:
    opened = BASE + timedelta(hours=4 * index)
    return Candle(
        symbol="TESTUSDT",
        timeframe="4h",
        open_time=opened,
        close_time=opened + timedelta(hours=4) - timedelta(milliseconds=1),
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal("100"),
        is_closed=closed,
    )


def setup_and_zone(
    known_at: datetime,
    side: SetupSide = SetupSide.SHORT,
) -> tuple[HTFSetup, FairValueGap]:
    fvg_side = FvgSide.BEARISH if side == SetupSide.SHORT else FvgSide.BULLISH
    zone = FairValueGap(
        id=uuid5(NAMESPACE_URL, f"zone:{side}"),
        symbol="TESTUSDT",
        timeframe="1d",
        side=fvg_side,
        formed_at=known_at - timedelta(days=1),
        known_at=known_at,
        lower=Decimal("10"),
        upper=Decimal("12"),
        midpoint=Decimal("11"),
        size=Decimal("2"),
        size_atr=1.0,
        source_candle_time=known_at - timedelta(days=1),
    )
    setup = HTFSetup(
        id=uuid5(NAMESPACE_URL, f"setup:{side}"),
        symbol="TESTUSDT",
        timeframe="1d",
        side=side,
        formed_at=known_at - timedelta(days=1),
        known_at=known_at,
        fvg_id=zone.id,
        displacement_id=uuid5(NAMESPACE_URL, f"d1-disp:{side}"),
        liquidity_context_id=uuid5(NAMESPACE_URL, f"context:{side}"),
        liquidity_classification=LiquidityContextType.LIQUIDITY_SWEEP,
        quality_score=6.0,
        context_score=2.0,
        displacement_score=3.0,
        fvg_score=0.5,
        structure_score=0.5,
        score_components={"all": 6.0},
        invalidation_price=Decimal("12") if side == SetupSide.SHORT else Decimal("10"),
        formed_bar_index=1,
        known_bar_index=1,
        expires_after_bar_index=91,
    )
    return setup, zone


def linked_impulse(
    candle: Candle, side: SetupSide, *, internal: bool = True
) -> tuple[Displacement, StructureBreak]:
    direction = Direction.BEARISH if side == SetupSide.SHORT else Direction.BULLISH
    break_id = uuid5(NAMESPACE_URL, f"break:{side}:{candle.open_time}")
    structure_break = StructureBreak(
        id=break_id,
        symbol=candle.symbol,
        timeframe="4h",
        direction=direction,
        kind=StructureBreakKind.MSS,
        level_type=StructureLevelType.INTERNAL if internal else StructureLevelType.EXTERNAL,
        broken_swing_id=uuid5(NAMESPACE_URL, f"swing:{side}"),
        level_price=Decimal("9") if side == SetupSide.SHORT else Decimal("13"),
        break_price=candle.close,
        formed_at=candle.open_time,
        known_at=candle.close_time,
        break_distance_atr=0.5,
        bar_index=1,
    )
    displacement = Displacement(
        id=uuid5(NAMESPACE_URL, f"disp:{side}:{candle.open_time}"),
        symbol=candle.symbol,
        timeframe="4h",
        direction=direction,
        start_time=candle.open_time,
        end_time=candle.open_time,
        known_at=candle.close_time,
        sequence_bars=1,
        score=5.0,
        body_atr=1.0,
        range_atr=1.2,
        net_move_atr=1.0,
        body_efficiency=0.8,
        directional_efficiency=0.8,
        close_location=0.1 if side == SetupSide.SHORT else 0.9,
        structure_break=True,
        structure_break_id=break_id,
        created_fvg=False,
        component_scores={"qualified": 5.0},
    )
    return displacement, structure_break


def replay(
    candles: list[Candle],
    config: AppConfig | None = None,
    side: SetupSide = SetupSide.SHORT,
    impulses: dict[datetime, tuple[Displacement, StructureBreak]] | None = None,
    known_at: datetime | None = None,
) -> tuple[H4ReactionEngine, Any]:
    setup, zone = setup_and_zone(known_at or BASE - timedelta(milliseconds=1), side)
    engine = H4ReactionEngine(setup, zone, config or AppConfig(), "test-hash")
    impulses = impulses or {}
    breaks = {item[1].id: item[1] for item in impulses.values()}
    for candle in candles:
        impulse = impulses.get(candle.close_time)
        engine.update(candle, 1.0, [impulse[0]] if impulse else [], breaks, {})
    return engine, engine.result()


@pytest.mark.parametrize(
    ("candle", "expected"),
    [
        (h4(0, "9", "10.2", "8.5", "9.5"), H4TouchType.WICK_TOUCH),
        (h4(0, "10.2", "10.4", "9", "9.5"), H4TouchType.BODY_ENTRY),
        (h4(0, "9", "10.4", "8.8", "10.2"), H4TouchType.CLOSE_INSIDE),
        (h4(0, "9", "11.2", "8.8", "9.5"), H4TouchType.MIDPOINT_REACHED),
        (h4(0, "9", "12.1", "8.8", "9.5"), H4TouchType.FULL_FILL),
        (h4(0, "11", "12.5", "10.5", "12.2"), H4TouchType.CLOSE_THROUGH),
    ],
)
def test_touch_type_taxonomy(candle: Candle, expected: H4TouchType) -> None:
    _engine, result = replay([candle])
    assert result[0][0].primary_touch_type == expected


def test_gap_over_zone_is_a_touch_type() -> None:
    _engine, result = replay([h4(0, "9", "9.5", "8.5", "9"), h4(1, "12.5", "13", "12.4", "12.5")])
    assert result[0][0].primary_touch_type == H4TouchType.GAP_OVER_ZONE


def test_touch_before_setup_activation_is_only_mitigation_metadata() -> None:
    before = h4(0, "9", "11", "8", "9.5")
    after = h4(1, "9", "9.8", "8.5", "9")
    _engine, result = replay([before, after], known_at=before.close_time)
    assert result[0] == []
    assert result[1] is None


def test_post_activation_touch_without_rejection_remains_zone_touched() -> None:
    _engine, result = replay([h4(0, "9", "10.5", "8.8", "10.25")])
    assert result[1].status == H4ReactionStatus.ZONE_TOUCHED
    assert result[1].first_reaction_at is None


def test_close_back_creates_early_reaction() -> None:
    candles = [h4(0, "9", "10.5", "8.8", "10.25"), h4(1, "10.2", "10.6", "9", "9.5")]
    _engine, result = replay(candles)
    assert result[1].status == H4ReactionStatus.EARLY_REACTION
    assert result[1].score_components["close_back"] > 0


def test_multiple_interactions_are_one_contiguous_touch_phase() -> None:
    candles = [h4(0, "9", "10.5", "8.8", "10.2"), h4(1, "10.2", "11", "9.8", "10.5")]
    _engine, result = replay(candles)
    assert len(result[0]) == 1
    assert result[0][0].bars_in_zone == 2


def test_pre_activation_mitigation_is_separate_from_post_touch() -> None:
    before = h4(0, "9", "11", "8.8", "9.5")
    after = h4(1, "9", "10.5", "8.8", "10.2")
    _engine, result = replay([before, after], known_at=before.close_time)
    assert result[0][0].pre_activation_mitigation_fraction == pytest.approx(0.5)
    assert result[0][0].post_activation_touch_fraction == pytest.approx(0.25)


def test_linked_displacement_and_internal_break_confirm_reaction() -> None:
    candle = h4(0, "10.5", "11", "8", "8.5")
    impulse = linked_impulse(candle, SetupSide.SHORT)
    _engine, result = replay([candle], impulses={candle.close_time: impulse})
    assert result[1].status == H4ReactionStatus.REACTION_CONFIRMED
    assert result[1].confirmed_at == candle.close_time
    assert result[2][0].canonical


def test_displacement_without_internal_break_is_rejected() -> None:
    candle = h4(0, "10.5", "11", "8", "8.5")
    impulse = linked_impulse(candle, SetupSide.SHORT, internal=False)
    _engine, result = replay([candle], impulses={candle.close_time: impulse})
    assert result[1].status == H4ReactionStatus.EARLY_REACTION
    assert "internal_structure_break" in result[3][0].reasons


def test_structure_break_without_displacement_does_not_confirm() -> None:
    _engine, result = replay([h4(0, "10.5", "11", "8", "8.5")])
    assert result[1].confirmed_at is None


def test_bullish_confirmation_is_symmetric() -> None:
    candle = h4(0, "11", "14", "10.5", "13.5")
    impulse = linked_impulse(candle, SetupSide.LONG)
    _engine, result = replay([candle], side=SetupSide.LONG, impulses={candle.close_time: impulse})
    assert result[1].status == H4ReactionStatus.REACTION_CONFIRMED


def test_one_wick_beyond_zone_does_not_invalidate() -> None:
    _engine, result = replay([h4(0, "9", "13", "8.5", "11.5")])
    assert result[1].status != H4ReactionStatus.INVALIDATED


def test_accepted_closes_beyond_zone_invalidate() -> None:
    candles = [h4(0, "11", "12.4", "10.5", "12.2"), h4(1, "12.2", "12.5", "12", "12.3")]
    _engine, result = replay(candles)
    assert result[1].status == H4ReactionStatus.INVALIDATED
    assert result[1].invalidation_reason == "accepted_close_through_zone"


def test_reclaim_resets_acceptance_sequence() -> None:
    candles = [h4(0, "11", "12.4", "10.5", "12.2"), h4(1, "12", "12.2", "11", "11.8")]
    _engine, result = replay(candles)
    assert result[1].status != H4ReactionStatus.INVALIDATED


def test_expiry_before_touch_is_counted_in_h4_bars() -> None:
    config = AppConfig().model_copy(
        update={
            "h4_reaction": AppConfig().h4_reaction.model_copy(
                update={"maximum_bars_activation_to_touch": 2}
            )
        }
    )
    _engine, result = replay([h4(0, "9", "9.5", "8", "9"), h4(1, "9", "9.5", "8", "9")], config)
    assert result[1].status == H4ReactionStatus.EXPIRED
    assert result[1].touch_at is None


def test_expiry_after_touch_without_confirmation() -> None:
    base = AppConfig()
    config = base.model_copy(
        update={
            "h4_reaction": base.h4_reaction.model_copy(
                update={"maximum_bars_touch_to_confirmation": 2}
            )
        }
    )
    candles = [h4(0, "9", "10.5", "8.8", "10.2"), h4(1, "10", "10.2", "9", "9.8")]
    _engine, result = replay(candles, config)
    assert result[1].status == H4ReactionStatus.EXPIRED
    assert result[1].expired_at == candles[1].close_time


def test_d1_zone_invalidation_cascades_to_h4_reaction() -> None:
    first = h4(0, "9", "10.5", "8.8", "10.2")
    second = h4(1, "10", "10.2", "9", "9.8")
    setup, zone = setup_and_zone(BASE - timedelta(milliseconds=1))
    zone = zone.model_copy(update={"invalidated_at": second.close_time})
    engine = H4ReactionEngine(setup, zone, AppConfig(), "hash")
    engine.update(first, 1.0, [], {}, {})
    engine.update(second, 1.0, [], {}, {})
    reaction = engine.result()[1]
    assert reaction is not None
    assert reaction.status == H4ReactionStatus.INVALIDATED
    assert reaction.invalidation_reason == "d1_setup_or_zone_invalidated"


def test_components_from_different_impulses_do_not_confirm() -> None:
    candle = h4(0, "10.5", "11", "8", "8.5")
    displacement, structure_break = linked_impulse(candle, SetupSide.SHORT)
    structure_break = structure_break.model_copy(
        update={"formed_at": candle.open_time - timedelta(hours=4)}
    )
    _engine, result = replay(
        [candle], impulses={candle.close_time: (displacement, structure_break)}
    )
    assert result[1].confirmed_at is None
    assert "same_impulse" in result[3][0].reasons


def test_overlapping_qualified_windows_have_one_canonical_candidate() -> None:
    first = h4(0, "10.5", "11", "8", "8.5")
    second = h4(1, "9", "10.5", "7.5", "8")
    impulses = {
        first.close_time: linked_impulse(first, SetupSide.SHORT),
        second.close_time: linked_impulse(second, SetupSide.SHORT),
    }
    _engine, result = replay([first, second], impulses=impulses)
    assert sum(item.canonical for item in result[2]) == 1
    assert len(result[4]) == 1
    assert result[4][0].reason == "MERGED_INTO_CANONICAL_H4_REACTION"


def test_depth_and_dwell_penalties_are_visible_in_score_components() -> None:
    candles = [
        h4(0, "9", "10.4", "8.8", "10.2"),
        h4(1, "10.2", "11.8", "9", "9.5"),
        h4(2, "9.5", "11.9", "9", "9.4"),
    ]
    _engine, result = replay(candles)
    components = result[1].score_components
    assert components["zone_depth_penalty"] < 0
    assert components["dwell_time_penalty"] < 0


def test_mandatory_h4_fvg_gate_rejects_unlinked_impulse() -> None:
    base = AppConfig()
    config = base.model_copy(
        update={"h4_reaction": base.h4_reaction.model_copy(update={"require_h4_fvg": True})}
    )
    candle = h4(0, "10.5", "11", "8", "8.5")
    impulse = linked_impulse(candle, SetupSide.SHORT)
    _engine, result = replay([candle], config, impulses={candle.close_time: impulse})
    assert result[1].confirmed_at is None
    assert "linked_h4_fvg" in result[3][0].reasons


def test_unclosed_candle_cannot_create_event() -> None:
    _engine, result = replay([h4(0, "9", "11", "8", "10.5", closed=False)])
    assert result[1] is None
    assert result[5] == []


def test_incremental_replay_is_deterministic() -> None:
    candle = h4(0, "10.5", "11", "8", "8.5")
    impulse = linked_impulse(candle, SetupSide.SHORT)
    first = replay([candle], impulses={candle.close_time: impulse})[1]
    second = replay([candle], impulses={candle.close_time: impulse})[1]
    assert [
        item.model_dump(mode="json") if hasattr(item, "model_dump") else item for item in first
    ] == [item.model_dump(mode="json") if hasattr(item, "model_dump") else item for item in second]


def test_batch_detector_sorts_input_and_reports_missing_intervals() -> None:
    setup, zone = setup_and_zone(BASE - timedelta(milliseconds=1))
    candles = [
        h4(0, "9", "9.5", "8.5", "9"),
        h4(1, "9", "10.2", "8.5", "9.5"),
        h4(3, "9", "9.5", "8.5", "9"),
    ]
    result = detect_h4_reactions(candles[::-1], [setup], [zone], AppConfig(), "hash")
    assert "UNORDERED_CANDLES" in result.diagnostics
    assert any(item.startswith("MISSING_INTERVAL") for item in result.diagnostics)


def test_quality_report_exposes_duplicates_incomplete_and_timeframe_mismatch() -> None:
    incomplete = h4(0, "9", "10", "8", "9", closed=False)
    mismatch = incomplete.model_copy(update={"timeframe": "1d", "is_closed": True})
    report = inspect_candle_quality([incomplete, incomplete, mismatch], "4h")
    assert any(item.startswith("DUPLICATE_CANDLE") for item in report.diagnostics)
    assert any(item.startswith("INCOMPLETE_CANDLE") for item in report.diagnostics)
    assert any(item.startswith("TIMEFRAME_MISMATCH") for item in report.diagnostics)
    with pytest.raises(ValueError, match="unsupported timeframe"):
        inspect_candle_quality([], "1h")


def test_reaction_state_machine_rejects_invalid_transition() -> None:
    with pytest.raises(ValueError, match="invalid H4 reaction transition"):
        H4ReactionStateMachine.transition(
            uuid5(NAMESPACE_URL, "reaction"),
            uuid5(NAMESPACE_URL, "setup"),
            H4ReactionStatus.WAITING_FOR_TOUCH,
            H4ReactionStatus.REACTION_CONFIRMED,
            BASE,
            BASE,
            0,
            "invalid",
        )
