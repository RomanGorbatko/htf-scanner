from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from htf_scanner.config import AppConfig, configuration_hash
from htf_scanner.detectors.d1_setup_detector import HTFSetupDetector
from htf_scanner.domain.enums import (
    Direction,
    FvgSide,
    LiquidityContextType,
    LiquidityInteractionType,
    ScannerRunStatus,
    StructureBreakKind,
    StructureLevelType,
    SwingSide,
)
from htf_scanner.domain.liquidity import LiquidityInteraction, LiquiditySequence
from htf_scanner.domain.outcome import SetupOutcome
from htf_scanner.domain.reaction import H4Reaction
from htf_scanner.domain.run import ScannerRun
from htf_scanner.domain.setup import MergedSetupCandidate, RejectedSetupCandidate
from htf_scanner.domain.structure import StructureBreak, StructurePromotion
from htf_scanner.storage.analysis_repository import AnalysisRepository
from htf_scanner.storage.database import create_database_engine
from htf_scanner.storage.models import (
    D1SetupCandidateRow,
    DisplacementRow,
    FvgRow,
    H4ReactionRow,
    HTFSetupRow,
    HTFSetupTransitionRow,
    LiquidityContextRow,
    LiquidityInteractionRow,
    LiquiditySequenceRow,
    MergedSetupCandidateRow,
    RejectedSetupCandidateRow,
    ScannerRunRow,
    SetupEventRow,
    SetupOutcomeRow,
    StructureBreakRow,
    StructurePromotionRow,
    SwingRow,
)
from tests.conftest import make_candle
from tests.factories import (
    make_context,
    make_displacement,
    make_fvg,
    make_swing,
)


def test_analysis_artifacts_are_persisted_idempotently(tmp_path) -> None:  # type: ignore[no-untyped-def]
    engine = create_database_engine(f"sqlite:///{tmp_path / 'analysis.db'}")
    repository = AnalysisRepository(engine)
    candle = make_candle(5, "9", "10", "6", "7")
    candles = [make_candle(index, "9", "10", "6", "7") for index in range(6)]
    fvg = make_fvg(candle, FvgSide.BEARISH)
    external = make_swing(candles, SwingSide.HIGH, "11", 0, 1)
    retracement = make_swing(candles, SwingSide.LOW, "8", 2, 3)
    swing = make_swing(candles, SwingSide.HIGH, "10", 3, 4)
    break_id = uuid5(NAMESPACE_URL, "repository-break")
    structure_break = StructureBreak(
        id=break_id,
        symbol=candle.symbol,
        timeframe="1d",
        direction=Direction.BEARISH,
        kind=StructureBreakKind.CHOCH,
        level_type=StructureLevelType.INTERNAL,
        broken_swing_id=retracement.id,
        level_price=Decimal("8"),
        break_price=Decimal("7"),
        formed_at=candle.open_time,
        known_at=candle.close_time,
        break_distance_atr=0.5,
        bar_index=5,
    )
    promotion = StructurePromotion(
        id=uuid5(NAMESPACE_URL, "repository-promotion"),
        symbol=candle.symbol,
        timeframe="1d",
        direction=Direction.BEARISH,
        promoted_swing_id=swing.id,
        replaced_external_swing_id=external.id,
        protected_swing_id=swing.id,
        caused_by_break_id=structure_break.id,
        promoted_at=candle.close_time,
        bar_index=5,
    )
    displacement = make_displacement(
        candle,
        Direction.BEARISH,
        fvg,
        structure_break_id=structure_break.id,
    )
    context = make_context(
        displacement,
        LiquidityContextType.FAILED_CONTINUATION_HIGH,
        2.5,
        external_reference_swing_id=external.id,
        attempt_swing_id=swing.id,
        retracement_swing_id=retracement.id,
        structure_break_id=structure_break.id,
    )
    interaction = LiquidityInteraction(
        id=uuid5(NAMESPACE_URL, "repository-interaction"),
        external_level_id=uuid5(NAMESPACE_URL, "repository-level"),
        reference_swing_id=external.id,
        symbol=candle.symbol,
        timeframe="1d",
        direction=Direction.BEARISH,
        event_type=LiquidityInteractionType.SWEPT,
        level_price=external.price,
        formed_at=candles[1].open_time,
        known_at=candles[1].close_time,
        candle_time=candles[1].open_time,
        bar_index=1,
        excursion_price=Decimal("0.2"),
        excursion_atr=0.1,
        close_relative_to_level=Decimal("-1"),
        closes_beyond_level=0,
        maximum_acceptance_distance_atr=0.1,
    )
    liquidity_sequence = LiquiditySequence(
        id=uuid5(NAMESPACE_URL, "repository-sequence"),
        sequence_key="repository-sequence",
        symbol=candle.symbol,
        timeframe="1d",
        direction=Direction.BEARISH,
        classification=LiquidityContextType.SWEEP_AND_FAILED_CONTINUATION,
        external_reference_swing_id=external.id,
        interaction_ids=[interaction.id],
        sweep_interaction_id=interaction.id,
        retracement_swing_id=retracement.id,
        attempt_swing_id=swing.id,
        broken_internal_swing_id=retracement.id,
        structure_break_id=structure_break.id,
        displacement_id=displacement.id,
        fvg_id=fvg.id,
        formed_at=swing.formed_at,
        known_at=candle.close_time,
        hard_gates={"test": True},
        failed_hard_gates=[],
        soft_feature_values={},
        score_penalties={},
        score_components={"test": 1.0},
        total_score=1.0,
    )
    config = AppConfig()
    config_hash = configuration_hash(config)
    setup, candidates, _merged, transitions, _rejected, events = HTFSetupDetector(
        config, config_hash
    ).detect(
        candles,
        [fvg],
        [external, retracement, swing],
        [structure_break],
        [displacement],
        [context],
    )
    rejected_candidate = RejectedSetupCandidate(
        id=uuid5(NAMESPACE_URL, "repository-rejected"),
        symbol=candle.symbol,
        timeframe="1d",
        side="short",
        displacement_id=displacement.id,
        rejected_at=candle.close_time,
        bar_index=5,
        reasons=["test_rejection"],
        diagnostics={},
    )
    merged_candidate = MergedSetupCandidate(
        id=uuid5(NAMESPACE_URL, "repository-merged"),
        sequence_key=candidates[0].sequence_key,
        symbol=candle.symbol,
        timeframe="1d",
        side="short",
        displacement_id=displacement.id,
        merged_into_candidate_id=candidates[0].id,
        known_at=candle.close_time,
    )
    reaction = H4Reaction(
        id=uuid5(NAMESPACE_URL, "reaction"),
        setup_id=setup[0].id,
        touch_at=candle.close_time,
        penetration_ratio=0.5,
        reaction_score=0,
        status="touched",
        features={},
    )
    outcome = SetupOutcome(
        id=uuid5(NAMESPACE_URL, "outcome"),
        setup_id=setup[0].id,
        anchor_type="touch",
        anchor_at=candle.close_time,
        evaluated_at=candle.close_time,
        metrics={},
        labels={},
    )
    run = ScannerRun(
        id=uuid5(NAMESPACE_URL, "run"),
        scanner_version="0.1.0",
        config_hash=config_hash,
        symbol=candle.symbol,
        timeframe="1d",
        start_at=candles[0].open_time,
        end_at=candle.close_time,
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        status=ScannerRunStatus.COMPLETED,
        counts={"setups": 1},
    )
    operations: list[tuple[Callable[[], int], int]] = [
        (lambda: repository.upsert_fvgs([fvg]), 1),
        (lambda: repository.upsert_swings([swing]), 1),
        (lambda: repository.upsert_structure_breaks([structure_break]), 1),
        (lambda: repository.upsert_structure_promotions([promotion]), 1),
        (lambda: repository.upsert_displacements([displacement]), 1),
        (lambda: repository.upsert_liquidity_interactions([interaction]), 1),
        (lambda: repository.upsert_liquidity_contexts([context]), 1),
        (lambda: repository.upsert_liquidity_sequences([liquidity_sequence]), 1),
        (lambda: repository.upsert_setup_candidates(candidates), 1),
        (lambda: repository.upsert_merged_candidates([merged_candidate]), 1),
        (lambda: repository.upsert_setups(setup), 1),
        (lambda: repository.upsert_setup_transitions(transitions), 2),
        (lambda: repository.upsert_rejected_candidates([rejected_candidate]), 1),
        (lambda: repository.upsert_reactions([reaction]), 1),
        (lambda: repository.upsert_outcomes([outcome]), 1),
        (lambda: repository.upsert_events(events), 1),
        (lambda: repository.upsert_runs([run]), 1),
    ]
    for operation, expected_count in operations:
        assert operation() == expected_count
        assert operation() == expected_count

    row_types = [
        FvgRow,
        SwingRow,
        StructureBreakRow,
        StructurePromotionRow,
        DisplacementRow,
        LiquidityInteractionRow,
        LiquidityContextRow,
        LiquiditySequenceRow,
        D1SetupCandidateRow,
        MergedSetupCandidateRow,
        HTFSetupRow,
        HTFSetupTransitionRow,
        RejectedSetupCandidateRow,
        H4ReactionRow,
        SetupOutcomeRow,
        SetupEventRow,
        ScannerRunRow,
    ]
    with Session(engine) as session:
        counts = [
            session.scalar(select(func.count()).select_from(row_type)) for row_type in row_types
        ]
        assert counts == [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2, 1, 1, 1, 1, 1]
    engine.dispose()


def test_configuration_hash_is_stable_and_sensitive() -> None:
    first = configuration_hash(AppConfig())
    second = configuration_hash(AppConfig())
    changed = configuration_hash(AppConfig.model_validate({"atr": {"period": 21}}))

    assert first == second
    assert len(first) == 64
    assert changed != first
