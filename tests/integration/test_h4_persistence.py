from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from htf_scanner.analytics.reaction_outcomes import evaluate_reaction_outcomes
from htf_scanner.config import AppConfig, AtrConfig, ReactionOutcomesConfig
from htf_scanner.detectors.h4_reaction_detector import H4ReactionEngine
from htf_scanner.domain.enums import BatchRunStatus, SetupSide
from htf_scanner.domain.run import BatchRun, BatchSymbolRun
from htf_scanner.storage.analysis_repository import AnalysisRepository
from htf_scanner.storage.database import create_database_engine
from htf_scanner.storage.models import (
    BatchRunRow,
    BatchSymbolRunRow,
    H4MergedCandidateRow,
    H4ReactionCandidateRow,
    H4ReactionRow,
    H4ReactionTransitionRow,
    H4TouchPhaseRow,
    ReactionOutcomeRow,
    ReactionTargetOutcomeRow,
)
from tests.unit.test_h4_reaction_engine import BASE, h4, linked_impulse, setup_and_zone


def test_h4_artifacts_and_batch_metadata_upsert_idempotently(tmp_path) -> None:  # type: ignore[no-untyped-def]
    config = AppConfig(
        atr=AtrConfig(period=1),
        reaction_outcomes=ReactionOutcomesConfig(horizons=[1], fixed_atr_targets=[1.0]),
    )
    setup, zone = setup_and_zone(BASE - timedelta(milliseconds=1), SetupSide.SHORT)
    first = h4(0, "10.5", "11", "8", "8.5")
    second = h4(1, "9", "10.5", "7.5", "8")
    first_impulse = linked_impulse(first, SetupSide.SHORT)
    second_impulse = linked_impulse(second, SetupSide.SHORT)
    breaks = {first_impulse[1].id: first_impulse[1], second_impulse[1].id: second_impulse[1]}
    reaction_engine = H4ReactionEngine(setup, zone, config, "hash")
    reaction_engine.update(first, 1.0, [first_impulse[0]], breaks, {})
    reaction_engine.update(second, 1.0, [second_impulse[0]], breaks, {})
    phases, reaction, candidates, _rejected, merged, transitions = reaction_engine.result()
    assert reaction is not None
    outcome_result = evaluate_reaction_outcomes(
        [reaction], [first, second], [setup], [zone], config, "hash"
    )
    batch_id = uuid5(NAMESPACE_URL, "persistence-batch")
    now = datetime(2026, 1, 2, tzinfo=UTC)
    batch = BatchRun(
        id=batch_id,
        config_hash="hash",
        symbols=[setup.symbol],
        started_at=BASE,
        completed_at=now,
        status=BatchRunStatus.COMPLETED,
        manifest_hash="manifest",
        counts={"symbols": 1},
    )
    symbol_run = BatchSymbolRun(
        id=uuid5(NAMESPACE_URL, "persistence-symbol-run"),
        batch_run_id=batch_id,
        symbol=setup.symbol,
        status=BatchRunStatus.COMPLETED,
        started_at=BASE,
        completed_at=now,
        runtime_ms=0,
        d1_candles=1,
        h4_candles=2,
        setup_count=1,
        reaction_count=1,
        outcome_count=1,
    )
    engine = create_database_engine(f"sqlite:///{tmp_path / 'h4.db'}")
    repository = AnalysisRepository(engine)
    repository.upsert_fvgs([zone])
    repository.upsert_setups([setup])
    operations: list[Callable[[], int]] = [
        lambda: repository.upsert_h4_touch_phases(phases, "run"),
        lambda: repository.upsert_reactions([reaction]),
        lambda: repository.upsert_h4_candidates(candidates, "run"),
        lambda: repository.upsert_h4_merged_candidates(merged, "run"),
        lambda: repository.upsert_h4_transitions(transitions, "run"),
        lambda: repository.upsert_reaction_outcomes(outcome_result.outcomes, "run"),
        lambda: repository.upsert_reaction_target_outcomes(outcome_result.target_outcomes, "run"),
        lambda: repository.upsert_batch_runs([batch]),
        lambda: repository.upsert_batch_symbol_runs([symbol_run]),
    ]
    for operation in operations:
        assert operation() > 0
        assert operation() > 0
    expected = [
        len(phases),
        1,
        len(candidates),
        len(merged),
        len(transitions),
        len(outcome_result.outcomes),
        len(outcome_result.target_outcomes),
        1,
        1,
    ]
    rows = [
        H4TouchPhaseRow,
        H4ReactionRow,
        H4ReactionCandidateRow,
        H4MergedCandidateRow,
        H4ReactionTransitionRow,
        ReactionOutcomeRow,
        ReactionTargetOutcomeRow,
        BatchRunRow,
        BatchSymbolRunRow,
    ]
    with Session(engine) as session:
        assert [session.scalar(select(func.count()).select_from(row)) for row in rows] == expected
    engine.dispose()
