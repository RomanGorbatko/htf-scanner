from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from htf_scanner.config import AppConfig, configuration_hash
from htf_scanner.data.cache import CandleFileCache
from htf_scanner.detectors.d1_setup_detector import detect_d1_setups
from htf_scanner.domain.enums import (
    LiquidityContextType,
    LiquidityInteractionType,
    SetupStatus,
)


def test_jto_july_2026_bearish_sequence_is_one_canonical_setup() -> None:
    fixture_root = Path(__file__).parents[1] / "fixtures"
    candles = CandleFileCache(fixture_root).read("JTOUSDT", "1d")
    config = AppConfig()
    config_hash = configuration_hash(config)

    first = detect_d1_setups(candles, config, config_hash)
    second = detect_d1_setups(candles, config, config_hash)
    setups = [
        setup
        for setup in first.setups
        if setup.side.value == "short"
        and datetime(2026, 7, 1, tzinfo=UTC) <= setup.formed_at < datetime(2026, 7, 16, tzinfo=UTC)
    ]

    assert first == second
    assert len(setups) == 1
    setup = setups[0]
    context = next(
        item for item in first.liquidity_contexts if item.id == setup.liquidity_context_id
    )
    sequence = next(
        item for item in first.liquidity_sequences if item.id == setup.liquidity_sequence_id
    )
    fvg = next(item for item in first.fvgs if item.id == setup.fvg_id)
    displacement = next(item for item in first.displacements if item.id == setup.displacement_id)
    interactions = {
        item.id: item
        for item in first.liquidity_interactions
        if item.id in setup.liquidity_interaction_ids
    }
    assert setup.sweep_interaction_id is not None
    sweep = interactions[setup.sweep_interaction_id]
    canonical = [
        item
        for item in first.setup_candidates
        if item.id == setup.canonical_candidate_id and item.canonical
    ]
    sequence_candidates = [
        item for item in first.setup_candidates if item.sequence_key == canonical[0].sequence_key
    ]
    merged = [
        item for item in first.merged_candidates if item.sequence_key == canonical[0].sequence_key
    ]

    assert setup.status == SetupStatus.ACTIVE
    assert setup.formed_at == datetime(2026, 7, 9, tzinfo=UTC)
    assert setup.known_at == datetime(2026, 7, 9, 23, 59, 59, 999000, tzinfo=UTC)
    assert setup.quality_score == sum(setup.score_components.values())
    assert setup.score_components["distance_penalty"] < 0
    assert setup.score_components["timing_penalty"] < 0
    assert context.classification == LiquidityContextType.SWEEP_AND_FAILED_CONTINUATION
    assert context.failed_hard_gates == []
    assert context.external_reference_price == Decimal("0.879500")
    assert context.retracement_price == Decimal("0.706000")
    assert context.attempt_price == Decimal("0.815300")
    assert sweep.event_type == LiquidityInteractionType.SWEPT
    assert sweep.formed_at == datetime(2026, 6, 26, tzinfo=UTC)
    assert sweep.level_price + sweep.excursion_price == Decimal("0.884900")
    assert sequence.broken_internal_swing_id == context.retracement_swing_id
    assert displacement.start_time == datetime(2026, 7, 8, tzinfo=UTC)
    assert displacement.end_time == datetime(2026, 7, 9, tzinfo=UTC)
    assert (fvg.lower, fvg.upper) == (Decimal("0.661600"), Decimal("0.720100"))
    assert len(canonical) == 1
    assert len(sequence_candidates) == 2
    assert sum(item.canonical for item in sequence_candidates) == 1
    assert canonical[0].sequence_bars == 2
    assert len(merged) == 1
