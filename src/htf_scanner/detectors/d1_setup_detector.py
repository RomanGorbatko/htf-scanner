from dataclasses import dataclass
from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from htf_scanner.config import AppConfig
from htf_scanner.detectors.displacement import DisplacementDetector
from htf_scanner.detectors.fvg_detector import detect_fvgs
from htf_scanner.detectors.setup_state_machine import HTFSetupStateMachine
from htf_scanner.domain.candle import Candle
from htf_scanner.domain.displacement import Displacement
from htf_scanner.domain.enums import (
    Direction,
    FvgSide,
    LiquidityContextType,
    SetupSide,
    SetupStatus,
    StructureLevelType,
)
from htf_scanner.domain.event import SetupEvent
from htf_scanner.domain.fvg import FairValueGap
from htf_scanner.domain.liquidity import (
    LiquidityContext,
    LiquidityInteraction,
    LiquiditySequence,
)
from htf_scanner.domain.setup import (
    D1SetupCandidate,
    HTFSetup,
    HTFSetupTransition,
    MergedSetupCandidate,
    RejectedSetupCandidate,
)
from htf_scanner.domain.structure import (
    MarketStructureSnapshot,
    StructureBreak,
    StructurePromotion,
)
from htf_scanner.domain.swing import SwingPoint
from htf_scanner.structure.causal_swings import detect_causal_swings
from htf_scanner.structure.liquidity_context import (
    ContinuationStructureContext,
    LiquidityContextClassifier,
)
from htf_scanner.structure.liquidity_interactions import detect_liquidity_interactions
from htf_scanner.structure.market_structure import detect_market_structure

VALID_REVERSAL_CONTEXTS = {
    LiquidityContextType.LIQUIDITY_SWEEP,
    LiquidityContextType.FAILED_CONTINUATION_HIGH,
    LiquidityContextType.FAILED_CONTINUATION_LOW,
    LiquidityContextType.SWEEP_AND_FAILED_CONTINUATION,
}


@dataclass(frozen=True)
class D1AnalysisResult:
    fvgs: list[FairValueGap]
    swings: list[SwingPoint]
    structure_breaks: list[StructureBreak]
    structure_promotions: list[StructurePromotion]
    structure_snapshots: list[MarketStructureSnapshot]
    displacements: list[Displacement]
    liquidity_interactions: list[LiquidityInteraction]
    liquidity_contexts: list[LiquidityContext]
    liquidity_sequences: list[LiquiditySequence]
    setup_candidates: list[D1SetupCandidate]
    merged_candidates: list[MergedSetupCandidate]
    setups: list[HTFSetup]
    setup_transitions: list[HTFSetupTransition]
    rejected_candidates: list[RejectedSetupCandidate]
    events: list[SetupEvent]


class HTFSetupDetector:
    def __init__(self, config: AppConfig, config_hash: str) -> None:
        self._config = config
        self._config_hash = config_hash
        self._state_machine = HTFSetupStateMachine()

    def detect(
        self,
        candles: list[Candle],
        fvgs: list[FairValueGap],
        swings: list[SwingPoint],
        structure_breaks: list[StructureBreak],
        displacements: list[Displacement],
        contexts: list[LiquidityContext],
    ) -> tuple[
        list[HTFSetup],
        list[D1SetupCandidate],
        list[MergedSetupCandidate],
        list[HTFSetupTransition],
        list[RejectedSetupCandidate],
        list[SetupEvent],
    ]:
        ordered = sorted(candles, key=lambda item: item.open_time)
        candle_indices = {candle.open_time: index for index, candle in enumerate(ordered)}
        close_indices = {candle.close_time: index for index, candle in enumerate(ordered)}
        contexts_by_displacement = {context.displacement_id: context for context in contexts}
        fvgs_by_id = {fvg.id: fvg for fvg in fvgs}
        swings_by_id = {swing.id: swing for swing in swings}
        breaks_by_id = {item.id: item for item in structure_breaks}
        displacements_by_id = {item.id: item for item in displacements}
        candidates = [
            self._candidate(
                displacement,
                fvgs_by_id.get(displacement.fvg_id) if displacement.fvg_id else None,
                contexts_by_displacement.get(displacement.id),
                breaks_by_id.get(displacement.structure_break_id)
                if displacement.structure_break_id
                else None,
                swings_by_id,
                candle_indices,
            )
            for displacement in displacements
        ]
        candidates, merged = self._canonicalize(candidates, displacements_by_id)
        canonical_ids = {item.id for item in candidates if item.canonical}
        setups: list[HTFSetup] = []
        transitions: list[HTFSetupTransition] = []
        rejected: list[RejectedSetupCandidate] = []
        events: list[SetupEvent] = []
        merged_by_displacement = {item.displacement_id: item for item in merged}
        for candidate in candidates:
            displacement = displacements_by_id[candidate.displacement_id]
            context = contexts_by_displacement.get(displacement.id)
            fvg = fvgs_by_id.get(candidate.fvg_id) if candidate.fvg_id else None
            if candidate.id not in canonical_ids:
                rejected.append(
                    self._rejected(
                        candidate,
                        displacement,
                        fvg,
                        context,
                        ["MERGED_INTO_CANONICAL_CANDIDATE"],
                        [],
                        candle_indices,
                        merged_by_displacement[displacement.id].merged_into_candidate_id,
                    )
                )
                continue
            if candidate.hard_rejection_reasons:
                rejected.append(
                    self._rejected(
                        candidate,
                        displacement,
                        fvg,
                        context,
                        candidate.hard_rejection_reasons,
                        candidate.hard_rejection_reasons,
                        candle_indices,
                    )
                )
                continue
            if candidate.total_score < self._config.d1_setup.minimum_quality_score:
                rejected.append(
                    self._rejected(
                        candidate,
                        displacement,
                        fvg,
                        context,
                        ["quality_score_below_minimum"],
                        [],
                        candle_indices,
                    )
                )
                continue
            assert fvg is not None and context is not None
            assert displacement.structure_break_id is not None
            structure_break = breaks_by_id[displacement.structure_break_id]
            setup = self._make_setup(
                candidate,
                displacement,
                fvg,
                context,
                structure_break,
                candle_indices,
            )
            setup, confirmed = self._state_machine.transition(
                setup,
                SetupStatus.CONFIRMED,
                setup.known_at,
                setup.known_bar_index,
                "mandatory_d1_components_confirmed",
            )
            setup, activated = self._state_machine.transition(
                setup,
                SetupStatus.ACTIVE,
                setup.known_at,
                setup.known_bar_index,
                "confirmed_fvg_available_for_future_h4_interaction",
            )
            transitions.extend([confirmed, activated])
            setup, terminal = self._terminal_state(setup, fvg, ordered, close_indices)
            if terminal is not None:
                transitions.append(terminal)
            setups.append(setup)
            events.append(self._make_event(setup))
        return setups, candidates, merged, transitions, rejected, events

    def _candidate(
        self,
        displacement: Displacement,
        fvg: FairValueGap | None,
        context: LiquidityContext | None,
        structure_break: StructureBreak | None,
        swings_by_id: dict[UUID, SwingPoint],
        candle_indices: dict[datetime, int],
    ) -> D1SetupCandidate:
        reasons = self._hard_validation_reasons(
            displacement,
            fvg,
            context,
            structure_break,
            swings_by_id,
            candle_indices,
        )
        side = SetupSide.LONG if displacement.direction == Direction.BULLISH else SetupSide.SHORT
        components = self._score_components(displacement, fvg, context, structure_break)
        sequence_key = self._sequence_key(displacement, fvg, context, structure_break, side)
        identity = f"setup-candidate:{sequence_key}:{displacement.id}"
        return D1SetupCandidate(
            id=uuid5(NAMESPACE_URL, identity),
            sequence_key=sequence_key,
            symbol=displacement.symbol,
            timeframe=displacement.timeframe,
            side=side,
            liquidity_sequence_id=context.liquidity_sequence_id if context else None,
            liquidity_context_id=context.id if context else None,
            external_reference_swing_id=(context.external_reference_swing_id if context else None),
            retracement_swing_id=context.retracement_swing_id if context else None,
            attempt_swing_id=context.attempt_swing_id if context else None,
            broken_internal_swing_id=(structure_break.broken_swing_id if structure_break else None),
            structure_break_id=structure_break.id if structure_break else None,
            displacement_id=displacement.id,
            fvg_id=fvg.id if fvg else None,
            known_at=max(
                item
                for item in (
                    displacement.known_at,
                    fvg.known_at if fvg else None,
                    context.known_at if context else None,
                    structure_break.known_at if structure_break else None,
                )
                if item is not None
            ),
            bar_index=candle_indices[displacement.end_time],
            sequence_bars=displacement.sequence_bars,
            hard_rejection_reasons=reasons,
            failed_hard_gates=context.failed_hard_gates if context else ["liquidity_context"],
            soft_feature_values=context.features if context else {},
            score_penalties=context.score_penalties if context else {},
            score_components=components,
            total_score=max(0.0, sum(components.values())),
        )

    @staticmethod
    def _canonicalize(
        candidates: list[D1SetupCandidate],
        displacements: dict[UUID, Displacement],
    ) -> tuple[list[D1SetupCandidate], list[MergedSetupCandidate]]:
        groups: dict[str, list[D1SetupCandidate]] = {}
        for candidate in candidates:
            groups.setdefault(candidate.sequence_key, []).append(candidate)
        result: list[D1SetupCandidate] = []
        merged: list[MergedSetupCandidate] = []
        for sequence_key in sorted(groups):
            group = groups[sequence_key]
            canonical = min(
                group,
                key=lambda item: (
                    item.structure_break_id is None,
                    item.fvg_id is None,
                    bool(item.hard_rejection_reasons),
                    item.known_at,
                    -item.total_score,
                    item.sequence_bars,
                    displacements[item.displacement_id].start_time,
                    str(item.id),
                ),
            )
            for candidate in group:
                is_canonical = candidate.id == canonical.id
                result.append(candidate.model_copy(update={"canonical": is_canonical}))
                if not is_canonical:
                    merged.append(
                        MergedSetupCandidate(
                            id=uuid5(
                                NAMESPACE_URL,
                                f"merged:{candidate.id}:{canonical.id}",
                            ),
                            sequence_key=sequence_key,
                            symbol=candidate.symbol,
                            timeframe=candidate.timeframe,
                            side=candidate.side,
                            displacement_id=candidate.displacement_id,
                            merged_into_candidate_id=canonical.id,
                            known_at=candidate.known_at,
                        )
                    )
        return sorted(result, key=lambda item: (item.known_at, str(item.id))), sorted(
            merged, key=lambda item: (item.known_at, str(item.id))
        )

    def _hard_validation_reasons(
        self,
        displacement: Displacement,
        fvg: FairValueGap | None,
        context: LiquidityContext | None,
        structure_break: StructureBreak | None,
        swings_by_id: dict[UUID, SwingPoint],
        candle_indices: dict[datetime, int],
    ) -> list[str]:
        reasons: list[str] = []
        if displacement.score < self._config.d1_setup.minimum_displacement_score:
            reasons.append("unqualified_displacement")
        if not displacement.structure_break or structure_break is None:
            reasons.append("missing_structure_break")
        if fvg is None:
            reasons.append("missing_linked_fvg")
        if context is None:
            reasons.append("missing_liquidity_context")
        else:
            reasons.extend(f"failed_gate:{item}" for item in context.failed_hard_gates)
            if context.classification not in VALID_REVERSAL_CONTEXTS:
                reasons.append(f"blocked_context:{context.classification.value}")
        if fvg is not None:
            expected_side = (
                FvgSide.BULLISH if displacement.direction == Direction.BULLISH else FvgSide.BEARISH
            )
            if fvg.side != expected_side:
                reasons.append("fvg_direction_mismatch")
            start_index = candle_indices[displacement.start_time]
            end_index = candle_indices[displacement.end_time]
            fvg_index = candle_indices.get(fvg.formed_at)
            if fvg_index is None or not start_index <= fvg_index <= end_index:
                reasons.append("fvg_outside_displacement_sequence")
            candidate_known_at = max(
                displacement.known_at,
                context.known_at if context else displacement.known_at,
                structure_break.known_at if structure_break else displacement.known_at,
            )
            if fvg.invalidated_at is not None and fvg.invalidated_at <= candidate_known_at:
                reasons.append("setup_already_invalidated")
        if structure_break is not None:
            start_index = candle_indices[displacement.start_time]
            end_index = candle_indices[displacement.end_time]
            if structure_break.direction != displacement.direction:
                reasons.append("structure_break_direction_mismatch")
            if structure_break.level_type != StructureLevelType.INTERNAL:
                reasons.append("structure_break_not_internal")
            if not (
                start_index
                <= structure_break.bar_index
                <= end_index + self._config.d1_setup.structure_break_max_lag_bars
            ):
                reasons.append("structure_break_outside_impulse_window")
        if context is not None and structure_break is not None:
            if context.structure_break_id != structure_break.id:
                reasons.append("context_structure_break_mismatch")
            attempt = (
                swings_by_id.get(context.attempt_swing_id) if context.attempt_swing_id else None
            )
            if attempt is None or context.retracement_swing_id is None:
                reasons.append("incomplete_continuation_sequence")
            else:
                if attempt.formed_at >= displacement.start_time:
                    reasons.append("displacement_did_not_start_after_attempt")
                if structure_break.broken_swing_id != context.retracement_swing_id:
                    reasons.append("wrong_internal_retracement_break")
        return list(dict.fromkeys(reasons))

    @staticmethod
    def _score_components(
        displacement: Displacement,
        fvg: FairValueGap | None,
        context: LiquidityContext | None,
        structure_break: StructureBreak | None,
    ) -> dict[str, float]:
        return {
            "structure": 1.5 if structure_break is not None else 0.0,
            "displacement": displacement.score,
            "fvg": min(1.5, fvg.size_atr) if fvg else 0.0,
            "failed_continuation": (
                context.component_scores.get("failed_continuation", 0.0) if context else 0.0
            ),
            "sweep_history": (
                context.component_scores.get("sweep_history", 0.0) if context else 0.0
            ),
            "freshness": (context.component_scores.get("freshness", 0.0) if context else 0.0),
            "distance_penalty": (
                context.score_penalties.get("distance_penalty", 0.0) if context else 0.0
            ),
            "timing_penalty": (
                context.score_penalties.get("timing_penalty", 0.0) if context else 0.0
            ),
        }

    @staticmethod
    def _sequence_key(
        displacement: Displacement,
        fvg: FairValueGap | None,
        context: LiquidityContext | None,
        structure_break: StructureBreak | None,
        side: SetupSide,
    ) -> str:
        if context is None:
            return f"{displacement.symbol}:{side.value}:unclassified:{displacement.id}"
        return ":".join(
            [
                displacement.symbol,
                side.value,
                str(context.external_reference_swing_id),
                str(context.retracement_swing_id),
                str(context.attempt_swing_id),
                str(structure_break.broken_swing_id if structure_break else None),
                str(fvg.id if fvg else structure_break.id if structure_break else displacement.id),
            ]
        )

    def _make_setup(
        self,
        candidate: D1SetupCandidate,
        displacement: Displacement,
        fvg: FairValueGap,
        context: LiquidityContext,
        structure_break: StructureBreak,
        candle_indices: dict[datetime, int],
    ) -> HTFSetup:
        formed_index = candle_indices[fvg.formed_at]
        known_index = max(
            candle_indices[displacement.end_time],
            structure_break.bar_index,
            candle_indices[fvg.formed_at],
        )
        known_at = max(
            fvg.known_at, displacement.known_at, context.known_at, structure_break.known_at
        )
        identity = f"htf-setup:{candidate.sequence_key}:{candidate.id}"
        return HTFSetup(
            id=uuid5(NAMESPACE_URL, identity),
            symbol=displacement.symbol,
            timeframe=displacement.timeframe,
            side=candidate.side,
            formed_at=fvg.formed_at,
            known_at=known_at,
            fvg_id=fvg.id,
            displacement_id=displacement.id,
            liquidity_context_id=context.id,
            liquidity_sequence_id=context.liquidity_sequence_id,
            canonical_candidate_id=candidate.id,
            liquidity_interaction_ids=context.interaction_ids,
            sweep_interaction_id=context.sweep_interaction_id,
            structure_break_id=structure_break.id,
            status=SetupStatus.CANDIDATE,
            liquidity_classification=context.classification,
            external_liquidity_remained=context.external_liquidity_remained,
            quality_score=candidate.total_score,
            context_score=context.score,
            displacement_score=displacement.score,
            fvg_score=candidate.score_components["fvg"],
            structure_score=candidate.score_components["structure"],
            score_components=candidate.score_components,
            invalidation_price=(fvg.lower if candidate.side == SetupSide.LONG else fvg.upper),
            formed_bar_index=formed_index,
            known_bar_index=known_index,
            expires_after_bar_index=known_index + self._config.d1_setup.max_setup_age_bars,
        )

    @staticmethod
    def _rejected(
        candidate: D1SetupCandidate,
        displacement: Displacement,
        fvg: FairValueGap | None,
        context: LiquidityContext | None,
        reasons: list[str],
        hard_reasons: list[str],
        candle_indices: dict[datetime, int],
        merged_into: UUID | None = None,
    ) -> RejectedSetupCandidate:
        identity = f"{candidate.id}:rejected:{'|'.join(reasons)}"
        diagnostics: dict[str, str | float | int | bool | None] = {
            "candidate_id": str(candidate.id),
            "sequence_key": candidate.sequence_key,
            "merged_into_candidate_id": str(merged_into) if merged_into else None,
            "displacement_score": displacement.score,
            "displacement_start": displacement.start_time.isoformat(),
            "displacement_end": displacement.end_time.isoformat(),
            "structure_break": displacement.structure_break,
            "context": context.classification.value if context else None,
            "context_score": context.score if context else None,
            "fvg_linked": fvg is not None,
            "fvg_lower": str(fvg.lower) if fvg else None,
            "fvg_upper": str(fvg.upper) if fvg else None,
        }
        if context is not None:
            diagnostics.update(
                {
                    "external_reference_swing_id": str(context.external_reference_swing_id)
                    if context.external_reference_swing_id
                    else None,
                    "attempt_swing_id": str(context.attempt_swing_id)
                    if context.attempt_swing_id
                    else None,
                    "retracement_swing_id": str(context.retracement_swing_id)
                    if context.retracement_swing_id
                    else None,
                    "sweep_interaction_id": str(context.sweep_interaction_id)
                    if context.sweep_interaction_id
                    else None,
                    "accepted_breakout": context.accepted_breakout,
                }
            )
        return RejectedSetupCandidate(
            id=uuid5(NAMESPACE_URL, identity),
            symbol=displacement.symbol,
            timeframe=displacement.timeframe,
            side=candidate.side,
            displacement_id=displacement.id,
            fvg_id=fvg.id if fvg else None,
            liquidity_context_id=context.id if context else None,
            rejected_at=displacement.known_at,
            bar_index=candle_indices[displacement.end_time],
            reasons=reasons,
            hard_rejection_reasons=hard_reasons,
            score_penalties=candidate.score_penalties,
            failed_hard_gates=candidate.failed_hard_gates,
            soft_feature_values=candidate.soft_feature_values,
            diagnostics=diagnostics,
        )

    def _terminal_state(
        self,
        setup: HTFSetup,
        fvg: FairValueGap,
        candles: list[Candle],
        close_indices: dict[datetime, int],
    ) -> tuple[HTFSetup, HTFSetupTransition | None]:
        unavailable_at = min(
            (item for item in (fvg.invalidated_at, fvg.full_fill_at) if item is not None),
            default=None,
        )
        expiry_index = setup.expires_after_bar_index
        expiry_at = candles[expiry_index].close_time if expiry_index < len(candles) else None
        if unavailable_at is not None and (expiry_at is None or unavailable_at <= expiry_at):
            reason = (
                "fvg_invalidated" if unavailable_at == fvg.invalidated_at else "fvg_fully_filled"
            )
            return self._state_machine.transition(
                setup,
                SetupStatus.INVALIDATED,
                unavailable_at,
                close_indices[unavailable_at],
                reason,
            )
        if expiry_at is not None:
            return self._state_machine.expire_if_due(setup, expiry_at, expiry_index)
        return setup, None

    def _make_event(self, setup: HTFSetup) -> SetupEvent:
        event_id = uuid5(
            NAMESPACE_URL, f"{setup.id}:D1_SETUP_ACTIVATED:{setup.known_at.isoformat()}"
        )
        return SetupEvent(
            id=event_id,
            setup_id=setup.id,
            event_type="D1_SETUP_ACTIVATED",
            event_time=setup.known_at,
            known_at=setup.known_at,
            payload={
                "side": setup.side.value,
                "quality_score": setup.quality_score,
                "liquidity_context": setup.liquidity_classification.value,
            },
            scanner_version=self._config.scanner.version,
            config_hash=self._config_hash,
        )


def _structure_contexts(
    swings: list[SwingPoint],
    breaks: list[StructureBreak],
    promotions: list[StructurePromotion],
    snapshots: list[MarketStructureSnapshot],
) -> dict[UUID, ContinuationStructureContext]:
    swings_by_id = {swing.id: swing for swing in swings}
    breaks_by_id = {item.id: item for item in breaks}
    result: dict[UUID, ContinuationStructureContext] = {}
    for promotion in promotions:
        if promotion.replaced_external_swing_id is None:
            continue
        structure_break = breaks_by_id[promotion.caused_by_break_id]
        snapshot_index = max(0, structure_break.bar_index - 1)
        result[structure_break.id] = ContinuationStructureContext(
            external_reference=swings_by_id[promotion.replaced_external_swing_id],
            retracement=swings_by_id[structure_break.broken_swing_id],
            continuation_attempt=swings_by_id[promotion.promoted_swing_id],
            structure_state=snapshots[snapshot_index],
            structure_break=structure_break,
            promotion=promotion,
        )
    return result


def detect_d1_setups(
    candles: list[Candle], config: AppConfig, config_hash: str
) -> D1AnalysisResult:
    ordered = sorted(candles, key=lambda item: item.open_time)
    fvgs = detect_fvgs(ordered, config.atr.period, config.fvg)
    swings = detect_causal_swings(ordered, config.atr.period, config.swings)
    structure_breaks, promotions, snapshots = detect_market_structure(
        ordered, swings, config.atr.period, config.structure
    )
    interactions = detect_liquidity_interactions(
        ordered, swings, snapshots, config.atr.period, config.liquidity
    )
    displacements = DisplacementDetector(config.displacement, config.atr.period).detect(
        ordered, structure_breaks, fvgs
    )
    explicit_contexts = _structure_contexts(swings, structure_breaks, promotions, snapshots)
    classifier = LiquidityContextClassifier(
        ordered, config.atr.period, config.liquidity, interactions
    )
    classified = [
        classifier.classify_with_sequence(
            displacement,
            explicit_contexts.get(displacement.structure_break_id)
            if displacement.structure_break_id
            else None,
        )
        for displacement in displacements
    ]
    contexts = [item[0] for item in classified]
    sequences_by_displacement = {item[1].displacement_id: item[1] for item in classified}
    setups, candidates, merged, transitions, rejected, events = HTFSetupDetector(
        config, config_hash
    ).detect(
        ordered,
        fvgs,
        swings,
        structure_breaks,
        displacements,
        contexts,
    )
    sequences_by_id = {item[1].id: item[1] for item in classified}
    for candidate in candidates:
        if candidate.canonical and candidate.liquidity_sequence_id is not None:
            sequences_by_id[candidate.liquidity_sequence_id] = sequences_by_displacement[
                candidate.displacement_id
            ]
    return D1AnalysisResult(
        fvgs=fvgs,
        swings=swings,
        structure_breaks=structure_breaks,
        structure_promotions=promotions,
        structure_snapshots=snapshots,
        displacements=displacements,
        liquidity_interactions=interactions,
        liquidity_contexts=contexts,
        liquidity_sequences=sorted(
            sequences_by_id.values(), key=lambda item: (item.known_at, str(item.id))
        ),
        setup_candidates=candidates,
        merged_candidates=merged,
        setups=setups,
        setup_transitions=transitions,
        rejected_candidates=rejected,
        events=events,
    )
