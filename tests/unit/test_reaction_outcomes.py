from datetime import timedelta
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from htf_scanner.analytics.reaction_outcomes import evaluate_reaction_outcomes
from htf_scanner.config import AppConfig, AtrConfig, ReactionOutcomesConfig
from htf_scanner.domain.enums import H4ReactionStatus, ReactionOutcomeLabel, SetupSide
from htf_scanner.domain.outcome import ReactionTargetReference
from htf_scanner.domain.reaction import H4Reaction
from tests.unit.test_h4_reaction_engine import BASE, h4, setup_and_zone


def confirmed_reaction(side: SetupSide, confirmed_at: object) -> H4Reaction:
    setup, zone = setup_and_zone(BASE - timedelta(milliseconds=1), side)
    timestamp = h4(1, "10", "10.5", "9.5", "10").close_time
    assert confirmed_at == timestamp
    return H4Reaction(
        id=uuid5(NAMESPACE_URL, f"outcome-reaction:{side}"),
        setup_id=setup.id,
        symbol=setup.symbol,
        side=side,
        status=H4ReactionStatus.REACTION_CONFIRMED,
        zone_id=zone.id,
        touch_open_time=h4(0, "10", "11", "9", "10").open_time,
        touch_close_time=h4(0, "10", "11", "9", "10").close_time,
        formed_at=h4(0, "10", "11", "9", "10").open_time,
        known_at=timestamp,
        confirmed_at=timestamp,
        entry_price_reference=Decimal("10"),
        reaction_extreme_price=Decimal("10"),
        config_hash="hash",
        created_at=timestamp,
        updated_at=timestamp,
    )


def outcome_config() -> AppConfig:
    return AppConfig(
        atr=AtrConfig(period=2),
        reaction_outcomes=ReactionOutcomesConfig(
            horizons=[2],
            fixed_atr_targets=[1.0],
            continuation_atr=1.0,
            failure_atr=1.0,
        ),
    )


def test_bearish_mfe_mae_and_times_are_directional() -> None:
    setup, zone = setup_and_zone(BASE - timedelta(milliseconds=1), SetupSide.SHORT)
    candles = [
        h4(0, "10", "11", "9", "10"),
        h4(1, "10", "10.5", "9.5", "10"),
        h4(2, "10", "10.5", "8", "9"),
        h4(3, "9", "11", "9", "10"),
    ]
    reaction = confirmed_reaction(SetupSide.SHORT, candles[1].close_time)
    result = evaluate_reaction_outcomes(
        [reaction], candles, [setup], [zone], outcome_config(), "hash"
    )
    outcome = result.outcomes[0]
    assert outcome.mfe_price == Decimal("2")
    assert outcome.mae_price == Decimal("1")
    assert outcome.bars_to_mfe == 1
    assert outcome.bars_to_mae == 2


def test_bullish_mfe_mae_are_mirrored() -> None:
    setup, zone = setup_and_zone(BASE - timedelta(milliseconds=1), SetupSide.LONG)
    candles = [
        h4(0, "10", "11", "9", "10"),
        h4(1, "10", "10.5", "9.5", "10"),
        h4(2, "10", "12", "9.5", "11"),
        h4(3, "11", "11", "9", "10"),
    ]
    reaction = confirmed_reaction(SetupSide.LONG, candles[1].close_time)
    outcome = evaluate_reaction_outcomes(
        [reaction], candles, [setup], [zone], outcome_config(), "hash"
    ).outcomes[0]
    assert outcome.mfe_price == Decimal("2")
    assert outcome.mae_price == Decimal("1")


def test_future_structural_target_is_not_used() -> None:
    setup, zone = setup_and_zone(BASE - timedelta(milliseconds=1), SetupSide.SHORT)
    candles = [
        h4(0, "10", "11", "9", "10"),
        h4(1, "10", "10.5", "9.5", "10"),
        h4(2, "10", "10.5", "8", "9"),
        h4(3, "9", "11", "9", "10"),
    ]
    reaction = confirmed_reaction(SetupSide.SHORT, candles[1].close_time)
    target = ReactionTargetReference(
        target_type="future_internal_liquidity",
        target_price=Decimal("8"),
        known_at=candles[2].close_time,
    )
    result = evaluate_reaction_outcomes(
        [reaction],
        candles,
        [setup],
        [zone],
        outcome_config(),
        "hash",
        {setup.id: [target]},
    )
    assert all(item.target_type != target.target_type for item in result.target_outcomes)


def test_known_target_reached_timestamp_and_adverse_excursion() -> None:
    setup, zone = setup_and_zone(BASE - timedelta(milliseconds=1), SetupSide.SHORT)
    candles = [
        h4(0, "10", "11", "9", "10"),
        h4(1, "10", "10.5", "9.5", "10"),
        h4(2, "10", "10.4", "8.5", "9"),
        h4(3, "9", "9.5", "8", "8.2"),
    ]
    reaction = confirmed_reaction(SetupSide.SHORT, candles[1].close_time)
    target = ReactionTargetReference(
        target_type="known_internal_liquidity",
        target_price=Decimal("8.25"),
        known_at=reaction.confirmed_at,
    )
    row = next(
        item
        for item in evaluate_reaction_outcomes(
            [reaction],
            candles,
            [setup],
            [zone],
            outcome_config(),
            "hash",
            {setup.id: [target]},
        ).target_outcomes
        if item.target_type == target.target_type
    )
    assert row.reached_at == candles[3].close_time
    assert row.bars_to_target == 2
    assert row.adverse_excursion_before_target == Decimal("0.4")


def test_completed_unresolved_horizon_gets_explicit_label() -> None:
    setup, zone = setup_and_zone(BASE - timedelta(milliseconds=1), SetupSide.SHORT)
    candles = [
        h4(0, "10", "11", "9", "10"),
        h4(1, "10", "10.5", "9.5", "10"),
        h4(2, "10", "10.1", "9.9", "10"),
        h4(3, "10", "10.1", "9.9", "10"),
    ]
    config = AppConfig(
        atr=AtrConfig(period=2),
        reaction_outcomes=ReactionOutcomesConfig(
            horizons=[2], fixed_atr_targets=[100.0], continuation_atr=10, failure_atr=10
        ),
    )
    reaction = confirmed_reaction(SetupSide.SHORT, candles[1].close_time)
    outcome = evaluate_reaction_outcomes(
        [reaction], candles, [setup], [zone], config, "hash"
    ).outcomes[0]
    assert ReactionOutcomeLabel.NO_RESOLUTION_WITHIN_HORIZON in outcome.labels


def test_outcome_snapshots_are_idempotent() -> None:
    setup, zone = setup_and_zone(BASE - timedelta(milliseconds=1), SetupSide.SHORT)
    candles = [
        h4(0, "10", "11", "9", "10"),
        h4(1, "10", "10.5", "9.5", "10"),
        h4(2, "10", "10.5", "8", "9"),
        h4(3, "9", "11", "9", "10"),
    ]
    reaction = confirmed_reaction(SetupSide.SHORT, candles[1].close_time)
    first = evaluate_reaction_outcomes(
        [reaction], candles, [setup], [zone], outcome_config(), "hash"
    )
    second = evaluate_reaction_outcomes(
        [reaction], candles, [setup], [zone], outcome_config(), "hash"
    )
    assert first == second
