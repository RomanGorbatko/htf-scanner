from dataclasses import dataclass
from decimal import Decimal
from math import isfinite
from uuid import NAMESPACE_URL, UUID, uuid5

from htf_scanner.config import AppConfig
from htf_scanner.domain.candle import Candle
from htf_scanner.domain.enums import ReactionOutcomeLabel, SetupSide
from htf_scanner.domain.fvg import FairValueGap
from htf_scanner.domain.outcome import (
    ReactionOutcome,
    ReactionTargetOutcome,
    ReactionTargetReference,
)
from htf_scanner.domain.reaction import H4Reaction
from htf_scanner.domain.setup import HTFSetup
from htf_scanner.indicators.candle_features import calculate_candle_features


@dataclass(frozen=True)
class ReactionOutcomeResult:
    outcomes: list[ReactionOutcome]
    target_outcomes: list[ReactionTargetOutcome]
    diagnostics: list[str]


def evaluate_reaction_outcomes(
    reactions: list[H4Reaction],
    candles: list[Candle],
    setups: list[HTFSetup],
    zones: list[FairValueGap],
    config: AppConfig,
    config_hash: str,
    extra_targets: dict[UUID, list[ReactionTargetReference]] | None = None,
) -> ReactionOutcomeResult:
    ordered = sorted((item for item in candles if item.is_closed), key=lambda item: item.open_time)
    features = calculate_candle_features(ordered, config.atr.period)
    candle_index = {item.close_time: index for index, item in enumerate(ordered)}
    setups_by_id = {item.id: item for item in setups}
    zones_by_id = {item.id: item for item in zones}
    extra_targets = extra_targets or {}
    outcomes: list[ReactionOutcome] = []
    target_outcomes: list[ReactionTargetOutcome] = []
    diagnostics: list[str] = []
    for reaction in sorted(
        reactions, key=lambda item: (item.confirmed_at or item.known_at, str(item.id))
    ):
        if reaction.confirmed_at is None:
            continue
        index = candle_index.get(reaction.confirmed_at)
        setup = setups_by_id.get(reaction.setup_id)
        zone = zones_by_id.get(reaction.zone_id) if reaction.zone_id is not None else None
        if index is None or setup is None:
            diagnostics.append(f"MISSING_CONFIRMATION_CONTEXT:{reaction.id}")
            continue
        atr = float(features.iloc[index]["atr"])
        if not isfinite(atr) or atr <= 0:
            diagnostics.append(f"MISSING_CONFIRMATION_ATR:{reaction.id}")
            continue
        reference = ordered[index].close
        targets = _targets(
            reaction,
            reference,
            atr,
            config.reaction_outcomes.fixed_atr_targets,
            extra_targets.get(reaction.setup_id, []),
        )
        for horizon in sorted(set(config.reaction_outcomes.horizons)):
            window = ordered[index + 1 : index + 1 + horizon]
            evaluated_at = window[-1].close_time if window else reaction.confirmed_at
            mfe, mae, bars_to_mfe, bars_to_mae = _excursions(reaction.side, reference, window)
            mfe_atr = float(mfe) / atr
            mae_atr = float(mae) / atr
            target_rows = _target_outcomes(
                reaction,
                targets,
                reference,
                window,
                horizon,
                config_hash,
            )
            labels = _labels(
                reaction.side,
                reference,
                window,
                mfe_atr,
                mae_atr,
                len(window) == horizon,
                zone,
                setup,
                target_rows,
                config,
            )
            outcome_id = uuid5(
                NAMESPACE_URL,
                f"reaction-outcome:{reaction.id}:{horizon}:{config_hash}",
            )
            outcome = ReactionOutcome(
                id=outcome_id,
                reaction_id=reaction.id,
                setup_id=reaction.setup_id,
                symbol=reaction.symbol,
                side=reaction.side,
                horizon_bars=horizon,
                reference_price=reference,
                atr_at_confirmation=Decimal(str(atr)),
                confirmed_at=reaction.confirmed_at,
                evaluated_at=evaluated_at,
                observed_bars=len(window),
                mfe_price=mfe,
                mfe_atr=mfe_atr,
                mae_price=mae,
                mae_atr=mae_atr,
                bars_to_mfe=bars_to_mfe,
                bars_to_mae=bars_to_mae,
                hours_to_mfe=bars_to_mfe * 4.0 if bars_to_mfe is not None else None,
                hours_to_mae=bars_to_mae * 4.0 if bars_to_mae is not None else None,
                labels=labels,
                config_hash=config_hash,
            )
            outcomes.append(outcome)
            target_outcomes.extend(
                item.model_copy(update={"outcome_id": outcome_id}) for item in target_rows
            )
    return ReactionOutcomeResult(
        outcomes=sorted(
            outcomes, key=lambda item: (item.confirmed_at, item.horizon_bars, str(item.id))
        ),
        target_outcomes=sorted(
            target_outcomes,
            key=lambda item: (item.known_at, item.horizon_bars, item.target_type, str(item.id)),
        ),
        diagnostics=sorted(diagnostics),
    )


def _targets(
    reaction: H4Reaction,
    reference: Decimal,
    atr: float,
    multiples: list[float],
    extra: list[ReactionTargetReference],
) -> list[ReactionTargetReference]:
    assert reaction.confirmed_at is not None
    known_extra = [item for item in extra if item.known_at <= reaction.confirmed_at]
    return _fixed_targets(reaction, reference, atr, multiples) + known_extra


def _fixed_targets(
    reaction: H4Reaction,
    reference: Decimal,
    atr: float,
    multiples: list[float],
) -> list[ReactionTargetReference]:
    assert reaction.confirmed_at is not None
    return [
        ReactionTargetReference(
            target_type=f"fixed_atr_{multiple:g}",
            target_price=(
                reference + Decimal(str(atr * multiple))
                if reaction.side == SetupSide.LONG
                else reference - Decimal(str(atr * multiple))
            ),
            known_at=reaction.confirmed_at,
        )
        for multiple in sorted(set(multiples))
    ]


def _excursions(
    side: SetupSide,
    reference: Decimal,
    window: list[Candle],
) -> tuple[Decimal, Decimal, int | None, int | None]:
    favorable = [
        max(Decimal("0"), candle.high - reference)
        if side == SetupSide.LONG
        else max(Decimal("0"), reference - candle.low)
        for candle in window
    ]
    adverse = [
        max(Decimal("0"), reference - candle.low)
        if side == SetupSide.LONG
        else max(Decimal("0"), candle.high - reference)
        for candle in window
    ]
    mfe = max(favorable, default=Decimal("0"))
    mae = max(adverse, default=Decimal("0"))
    return (
        mfe,
        mae,
        favorable.index(mfe) + 1 if favorable and mfe > 0 else None,
        adverse.index(mae) + 1 if adverse and mae > 0 else None,
    )


def _target_outcomes(
    reaction: H4Reaction,
    targets: list[ReactionTargetReference],
    reference: Decimal,
    window: list[Candle],
    horizon: int,
    config_hash: str,
) -> list[ReactionTargetOutcome]:
    rows: list[ReactionTargetOutcome] = []
    for target in targets:
        target_above_reference = target.target_price >= reference
        reached_index = next(
            (
                index
                for index, candle in enumerate(window)
                if (
                    candle.high >= target.target_price
                    if target_above_reference
                    else candle.low <= target.target_price
                )
            ),
            None,
        )
        prefix = window[: reached_index + 1] if reached_index is not None else window
        adverse = max(
            (
                max(Decimal("0"), reference - candle.low)
                if reaction.side == SetupSide.LONG
                else max(Decimal("0"), candle.high - reference)
                for candle in prefix
            ),
            default=Decimal("0"),
        )
        identity = (
            f"reaction-target:{reaction.id}:{horizon}:{target.target_type}:{target.target_price}"
        )
        rows.append(
            ReactionTargetOutcome(
                id=uuid5(NAMESPACE_URL, identity),
                reaction_id=reaction.id,
                outcome_id=UUID(int=0),
                setup_id=reaction.setup_id,
                target_type=target.target_type,
                target_price=target.target_price,
                known_at=target.known_at,
                horizon_bars=horizon,
                reached_at=window[reached_index].close_time if reached_index is not None else None,
                bars_to_target=reached_index + 1 if reached_index is not None else None,
                adverse_excursion_before_target=adverse,
                config_hash=config_hash,
            )
        )
    return rows


def _labels(
    side: SetupSide,
    reference: Decimal,
    window: list[Candle],
    mfe_atr: float,
    mae_atr: float,
    complete_horizon: bool,
    zone: FairValueGap | None,
    setup: HTFSetup,
    targets: list[ReactionTargetOutcome],
    config: AppConfig,
) -> list[ReactionOutcomeLabel]:
    labels: list[ReactionOutcomeLabel] = []
    if mfe_atr >= config.reaction_outcomes.continuation_atr:
        labels.append(ReactionOutcomeLabel.REACTION_CONTINUED)
    if mae_atr >= config.reaction_outcomes.failure_atr:
        labels.append(ReactionOutcomeLabel.REACTION_FAILED)
    if zone is not None and any(
        candle.high >= zone.lower and candle.low <= zone.upper for candle in window
    ):
        labels.append(ReactionOutcomeLabel.ZONE_RETESTED)
    invalidation = any(
        candle.high >= setup.invalidation_price
        if side == SetupSide.SHORT
        else candle.low <= setup.invalidation_price
        for candle in window
    )
    if invalidation:
        labels.append(ReactionOutcomeLabel.INVALIDATION_REACHED)
    if any(item.reached_at is not None for item in targets):
        labels.append(ReactionOutcomeLabel.D1_TARGET_REACHED)
    if complete_horizon and not any(
        item
        in {
            ReactionOutcomeLabel.REACTION_CONTINUED,
            ReactionOutcomeLabel.REACTION_FAILED,
            ReactionOutcomeLabel.D1_TARGET_REACHED,
        }
        for item in labels
    ):
        labels.append(ReactionOutcomeLabel.NO_RESOLUTION_WITHIN_HORIZON)
    _ = reference
    return labels
