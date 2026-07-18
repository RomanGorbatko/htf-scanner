from dataclasses import dataclass
from uuid import UUID

from htf_scanner.analytics.reaction_outcomes import (
    ReactionOutcomeResult,
    evaluate_reaction_outcomes,
)
from htf_scanner.config import AppConfig
from htf_scanner.data.binance_rest import validate_candles
from htf_scanner.detectors.d1_setup_detector import D1AnalysisResult, detect_d1_setups
from htf_scanner.detectors.h4_reaction_detector import H4AnalysisResult, detect_h4_reactions
from htf_scanner.domain.candle import Candle
from htf_scanner.domain.enums import SetupSide
from htf_scanner.domain.outcome import ReactionTargetReference


@dataclass(frozen=True)
class SymbolAnalysisResult:
    d1: D1AnalysisResult
    h4: H4AnalysisResult
    outcomes: ReactionOutcomeResult


def analyze_symbol(
    d1_candles: list[Candle],
    h4_candles: list[Candle],
    config: AppConfig,
    config_hash: str,
    *,
    strict_data: bool = False,
) -> SymbolAnalysisResult:
    ordered_d1 = validate_candles(d1_candles, "1d")
    d1 = detect_d1_setups(ordered_d1, config, config_hash)
    h4 = detect_h4_reactions(
        h4_candles,
        d1.setups,
        d1.fvgs,
        config,
        config_hash,
        strict_data=strict_data,
    )
    outcomes = evaluate_reaction_outcomes(
        h4.reactions,
        h4_candles,
        d1.setups,
        d1.fvgs,
        config,
        config_hash,
        _causal_d1_targets(d1_candles, h4_candles, d1, h4),
    )
    return SymbolAnalysisResult(d1=d1, h4=h4, outcomes=outcomes)


def _causal_d1_targets(
    d1_candles: list[Candle],
    h4_candles: list[Candle],
    d1: D1AnalysisResult,
    h4: H4AnalysisResult,
) -> dict[UUID, list[ReactionTargetReference]]:
    setups = {item.id: item for item in d1.setups}
    displacements = {item.id: item for item in d1.displacements}
    d1_by_open = {item.open_time: item for item in d1_candles}
    h4_by_close = {item.close_time: item for item in h4_candles}
    targets: dict[UUID, list[ReactionTargetReference]] = {}
    for reaction in h4.reactions:
        if reaction.confirmed_at is None:
            continue
        setup = setups[reaction.setup_id]
        confirmation_candle = h4_by_close.get(reaction.confirmed_at)
        if confirmation_candle is None:
            continue
        references: list[ReactionTargetReference] = []
        displacement = displacements.get(setup.displacement_id)
        impulse_candle = d1_by_open.get(displacement.start_time) if displacement else None
        if displacement is not None and impulse_candle is not None:
            references.append(
                ReactionTargetReference(
                    target_type="setup_impulse_origin",
                    target_price=impulse_candle.open,
                    known_at=setup.known_at,
                )
            )
        snapshots = [
            item for item in d1.structure_snapshots if item.known_at <= reaction.confirmed_at
        ]
        if snapshots:
            snapshot = snapshots[-1]
            if setup.side == SetupSide.SHORT:
                levels = (
                    ("nearest_opposing_d1_internal_liquidity", snapshot.internal_low),
                    ("nearest_opposing_d1_external_liquidity", snapshot.external_low),
                )
            else:
                levels = (
                    ("nearest_opposing_d1_internal_liquidity", snapshot.internal_high),
                    ("nearest_opposing_d1_external_liquidity", snapshot.external_high),
                )
            references.extend(
                ReactionTargetReference(
                    target_type=target_type,
                    target_price=price,
                    known_at=snapshot.known_at,
                )
                for target_type, price in levels
                if price is not None
                and (
                    price < confirmation_candle.close
                    if setup.side == SetupSide.SHORT
                    else price > confirmation_candle.close
                )
            )
        unique = {(item.target_type, item.target_price, item.known_at): item for item in references}
        targets[reaction.setup_id] = sorted(
            unique.values(), key=lambda item: (item.target_type, item.target_price, item.known_at)
        )
    return targets
