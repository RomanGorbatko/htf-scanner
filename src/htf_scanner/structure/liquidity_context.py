from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from htf_scanner.config import LiquidityConfig
from htf_scanner.domain.candle import Candle
from htf_scanner.domain.displacement import Displacement
from htf_scanner.domain.enums import (
    Direction,
    LiquidityContextType,
    LiquidityInteractionType,
    StructureLevelType,
    SwingSide,
)
from htf_scanner.domain.liquidity import (
    LiquidityContext,
    LiquidityInteraction,
    LiquiditySequence,
)
from htf_scanner.domain.structure import (
    MarketStructureSnapshot,
    StructureBreak,
    StructurePromotion,
)
from htf_scanner.domain.swing import SwingPoint
from htf_scanner.indicators.candle_features import calculate_candle_features


@dataclass(frozen=True)
class ContinuationStructureContext:
    external_reference: SwingPoint
    retracement: SwingPoint
    continuation_attempt: SwingPoint
    structure_state: MarketStructureSnapshot
    structure_break: StructureBreak
    promotion: StructurePromotion


class LiquidityContextClassifier:
    """Classify explicit structural sequences using hard gates and soft penalties."""

    def __init__(
        self,
        candles: list[Candle],
        atr_period: int,
        config: LiquidityConfig,
        interactions: list[LiquidityInteraction] | None = None,
        atr_values: list[float] | None = None,
    ) -> None:
        self._candles = sorted(candles, key=lambda item: item.open_time)
        self._config = config
        if atr_values is not None and len(atr_values) != len(self._candles):
            raise ValueError("one ATR value is required per candle")
        self._atr_values = (
            atr_values
            if atr_values is not None
            else [
                float(item) for item in calculate_candle_features(self._candles, atr_period)["atr"]
            ]
        )
        self._indices = {candle.open_time: index for index, candle in enumerate(self._candles)}
        self._interactions = interactions or []

    def classify(
        self,
        displacement: Displacement,
        structure: ContinuationStructureContext | None,
    ) -> LiquidityContext:
        return self.classify_with_sequence(displacement, structure)[0]

    def classify_with_sequence(
        self,
        displacement: Displacement,
        structure: ContinuationStructureContext | None,
    ) -> tuple[LiquidityContext, LiquiditySequence]:
        end_index = self._indices[displacement.end_time]
        atr = self._atr_values[end_index]
        if structure is None or atr <= 0:
            return self._no_clear(displacement)
        reference = structure.external_reference
        attempt = structure.continuation_attempt
        retracement = structure.retracement
        local_window = self._candles[attempt.bar_index : end_index + 1]
        signed_break = self._signed_break(reference, attempt, displacement.direction)
        distance_atr = abs(signed_break / atr)
        closes_beyond_flags = [
            self._close_beyond(candle, reference, displacement.direction) for candle in local_window
        ]
        closes_beyond = sum(closes_beyond_flags)
        holding_bars = self._maximum_consecutive(closes_beyond_flags)
        maximum_excursion_atr = max(
            (
                self._excursion(candle, reference, displacement.direction) / atr
                for candle in local_window
            ),
            default=0.0,
        )
        local_accepted = (
            closes_beyond >= self._config.accepted_breakout_min_closes
            and holding_bars >= self._config.accepted_breakout_min_closes
            and maximum_excursion_atr >= self._config.accepted_breakout_min_atr
        )
        relevant_interactions = [
            interaction
            for interaction in self._interactions
            if interaction.reference_swing_id == reference.id
            and interaction.known_at <= displacement.known_at
        ]
        accepted_events = [
            interaction
            for interaction in relevant_interactions
            if interaction.event_type == LiquidityInteractionType.ACCEPTED_BEYOND
            and interaction.known_at <= attempt.known_at
        ]
        reclaimed_events = [
            interaction
            for interaction in relevant_interactions
            if interaction.event_type == LiquidityInteractionType.RECLAIMED
            and interaction.known_at <= attempt.known_at
        ]
        last_accepted_at = max(
            (interaction.known_at for interaction in accepted_events), default=None
        )
        last_reclaimed_at = max(
            (interaction.known_at for interaction in reclaimed_events), default=None
        )
        accepted_history_active = last_accepted_at is not None and (
            last_reclaimed_at is None or last_accepted_at > last_reclaimed_at
        )
        accepted = local_accepted or accepted_history_active
        sweep_events = [
            interaction
            for interaction in relevant_interactions
            if interaction.event_type == LiquidityInteractionType.SWEPT
            and interaction.known_at <= attempt.known_at
        ]
        sweep_event = max(sweep_events, key=lambda item: item.known_at, default=None)
        hard_gates = self._hard_gates(displacement, structure, accepted)
        failed_hard_gates = [name for name, passed in hard_gates.items() if not passed]
        failed_continuation = not failed_hard_gates
        unswept = signed_break <= 0
        classification = self._classification(
            displacement.direction,
            accepted,
            sweep_event is not None,
            failed_continuation,
            unswept,
        )
        bars_to_displacement = end_index - attempt.bar_index
        retracement_size_atr = abs(float(reference.price - retracement.price)) / atr
        attempt_quality = max(
            0.0,
            1.0 - distance_atr / max(self._config.failed_continuation_max_distance_atr * 3.0, 1e-9),
        )
        freshness = 1.0 / (
            1.0
            + bars_to_displacement / max(float(self._config.failed_continuation_followup_bars), 1.0)
        )
        soft_features: dict[str, float | int | bool | None] = {
            "distance_attempt_to_external_atr": distance_atr,
            "excursion_beyond_external_atr": max(0.0, signed_break / atr),
            "retracement_size_atr": retracement_size_atr,
            "bars_external_to_retracement": retracement.bar_index - reference.bar_index,
            "bars_retracement_to_attempt": attempt.bar_index - retracement.bar_index,
            "bars_attempt_to_displacement": bars_to_displacement,
            "continuation_attempt_quality": attempt_quality,
            "prior_sweep_history": sweep_event is not None,
            "closes_beyond_external": closes_beyond,
            "maximum_acceptance_distance_atr": maximum_excursion_atr,
            "acceptance_holding_bars": holding_bars,
            "accepted_breakout": accepted,
            "local_accepted_breakout": local_accepted,
            "active_accepted_breakout_history": accepted_history_active,
            "displacement_score": displacement.score,
            "displacement_body_atr": displacement.body_atr,
            "displacement_range_atr": displacement.range_atr,
            "freshness": freshness,
        }
        penalties = {
            "distance_penalty": self._soft_penalty(
                distance_atr,
                self._config.failed_continuation_max_distance_atr,
                self._config.distance_penalty_max,
            ),
            "timing_penalty": self._soft_penalty(
                float(bars_to_displacement),
                float(self._config.failed_continuation_followup_bars),
                self._config.timing_penalty_max,
            ),
        }
        components = self._components(
            failed_continuation,
            sweep_event is not None,
            retracement_size_atr,
            attempt_quality,
            freshness,
            penalties,
        )
        sequence_key = self._sequence_key(displacement, structure)
        sequence_id = uuid5(NAMESPACE_URL, f"liquidity-sequence:{sequence_key}")
        sequence = LiquiditySequence(
            id=sequence_id,
            sequence_key=sequence_key,
            symbol=displacement.symbol,
            timeframe=displacement.timeframe,
            direction=displacement.direction,
            classification=classification,
            external_reference_swing_id=reference.id,
            interaction_ids=[item.id for item in relevant_interactions],
            sweep_interaction_id=sweep_event.id if sweep_event else None,
            retracement_swing_id=retracement.id,
            attempt_swing_id=attempt.id,
            broken_internal_swing_id=structure.structure_break.broken_swing_id,
            structure_break_id=structure.structure_break.id,
            displacement_id=displacement.id,
            fvg_id=displacement.fvg_id,
            formed_at=attempt.formed_at,
            known_at=max(displacement.known_at, structure.structure_break.known_at),
            hard_gates=hard_gates,
            failed_hard_gates=failed_hard_gates,
            soft_feature_values=soft_features,
            score_penalties=penalties,
            score_components=components,
            total_score=max(0.0, sum(components.values())),
        )
        identity = f"liquidity-context:{sequence_id}:{displacement.id}:{classification.value}"
        context = LiquidityContext(
            id=uuid5(NAMESPACE_URL, identity),
            displacement_id=displacement.id,
            symbol=displacement.symbol,
            timeframe=displacement.timeframe,
            reversal_direction=displacement.direction,
            classification=classification,
            formed_at=attempt.formed_at,
            known_at=sequence.known_at,
            external_reference_swing_id=reference.id,
            external_reference_price=reference.price,
            external_reference_formed_at=reference.formed_at,
            attempt_swing_id=attempt.id,
            attempt_price=attempt.price,
            attempt_formed_at=attempt.formed_at,
            retracement_swing_id=retracement.id,
            retracement_price=retracement.price,
            retracement_formed_at=retracement.formed_at,
            structure_break_id=structure.structure_break.id,
            liquidity_sequence_id=sequence.id,
            interaction_ids=sequence.interaction_ids,
            sweep_interaction_id=sequence.sweep_interaction_id,
            sweep=sweep_event is not None,
            accepted_breakout=accepted,
            external_liquidity_remained=unswept,
            score=sequence.total_score,
            component_scores=components,
            features=soft_features,
            hard_gates=hard_gates,
            failed_hard_gates=failed_hard_gates,
            score_penalties=penalties,
        )
        return context, sequence

    def _hard_gates(
        self,
        displacement: Displacement,
        structure: ContinuationStructureContext,
        accepted: bool,
    ) -> dict[str, bool]:
        reference = structure.external_reference
        retracement = structure.retracement
        attempt = structure.continuation_attempt
        expected_side = (
            SwingSide.HIGH if displacement.direction == Direction.BEARISH else SwingSide.LOW
        )
        active_external_id = (
            structure.structure_state.external_high_id
            if expected_side == SwingSide.HIGH
            else structure.structure_state.external_low_id
        )
        return {
            "active_external_reference": active_external_id == reference.id,
            "confirmed_retracement": retracement.side != expected_side,
            "confirmed_continuation_attempt": attempt.side == expected_side,
            "causal_swing_order": (reference.bar_index < retracement.bar_index < attempt.bar_index),
            "no_accepted_breakout": not accepted,
            "opposite_displacement_after_attempt": (attempt.formed_at < displacement.start_time),
            "relevant_internal_close_break": (
                structure.structure_break.direction == displacement.direction
                and structure.structure_break.level_type == StructureLevelType.INTERNAL
                and structure.structure_break.broken_swing_id == retracement.id
                and structure.structure_break.id == displacement.structure_break_id
            ),
            "causal_promotion": (
                structure.promotion.caused_by_break_id == structure.structure_break.id
                and structure.promotion.promoted_swing_id == attempt.id
                and structure.promotion.replaced_external_swing_id == reference.id
            ),
            "linked_same_impulse_fvg": (
                displacement.created_fvg and displacement.fvg_id is not None
            ),
        }

    @staticmethod
    def _classification(
        direction: Direction,
        accepted: bool,
        swept: bool,
        failed: bool,
        unswept: bool,
    ) -> LiquidityContextType:
        if accepted:
            return LiquidityContextType.ACCEPTED_BREAKOUT
        if swept and failed:
            return LiquidityContextType.SWEEP_AND_FAILED_CONTINUATION
        if failed:
            return (
                LiquidityContextType.FAILED_CONTINUATION_HIGH
                if direction == Direction.BEARISH
                else LiquidityContextType.FAILED_CONTINUATION_LOW
            )
        if swept:
            return LiquidityContextType.LIQUIDITY_SWEEP
        if unswept:
            return LiquidityContextType.UNSWEPT_EXTERNAL_LIQUIDITY
        return LiquidityContextType.NO_CLEAR_CONTEXT

    def _components(
        self,
        failed: bool,
        swept: bool,
        retracement_size_atr: float,
        attempt_quality: float,
        freshness: float,
        penalties: dict[str, float],
    ) -> dict[str, float]:
        if not failed:
            return {}
        retracement_quality = min(
            1.0,
            retracement_size_atr / max(self._config.minimum_retracement_atr, 1e-9),
        )
        return {
            "failed_continuation": 1.5 + 0.5 * retracement_quality + 0.5 * attempt_quality,
            "sweep_history": 1.5 if swept else 0.0,
            "freshness": freshness,
            **penalties,
        }

    @staticmethod
    def _soft_penalty(value: float, threshold: float, maximum: float) -> float:
        if threshold <= 0 or value <= threshold:
            return 0.0
        return -min(maximum, ((value - threshold) / threshold) * maximum)

    @staticmethod
    def _sequence_key(
        displacement: Displacement,
        structure: ContinuationStructureContext,
    ) -> str:
        return ":".join(
            [
                displacement.symbol,
                displacement.direction.value,
                str(structure.external_reference.id),
                str(structure.retracement.id),
                str(structure.continuation_attempt.id),
                str(structure.structure_break.broken_swing_id),
                str(displacement.fvg_id or structure.structure_break.id),
            ]
        )

    def _no_clear(self, displacement: Displacement) -> tuple[LiquidityContext, LiquiditySequence]:
        sequence_key = f"{displacement.symbol}:{displacement.direction.value}:{displacement.id}"
        sequence_id = uuid5(NAMESPACE_URL, f"liquidity-sequence:{sequence_key}")
        hard_gates = {
            "active_external_reference": False,
            "confirmed_retracement": False,
            "confirmed_continuation_attempt": False,
            "causal_swing_order": False,
            "no_accepted_breakout": True,
            "opposite_displacement_after_attempt": False,
            "relevant_internal_close_break": displacement.structure_break,
            "causal_promotion": False,
            "linked_same_impulse_fvg": displacement.created_fvg,
        }
        failed = [name for name, passed in hard_gates.items() if not passed]
        sequence = LiquiditySequence(
            id=sequence_id,
            sequence_key=sequence_key,
            symbol=displacement.symbol,
            timeframe=displacement.timeframe,
            direction=displacement.direction,
            classification=LiquidityContextType.NO_CLEAR_CONTEXT,
            displacement_id=displacement.id,
            fvg_id=displacement.fvg_id,
            formed_at=displacement.start_time,
            known_at=displacement.known_at,
            hard_gates=hard_gates,
            failed_hard_gates=failed,
            soft_feature_values={"prior_sweep_history": False},
            score_penalties={},
            score_components={},
            total_score=0.0,
        )
        context = LiquidityContext(
            id=uuid5(NAMESPACE_URL, f"{displacement.id}:no-clear-context"),
            displacement_id=displacement.id,
            symbol=displacement.symbol,
            timeframe=displacement.timeframe,
            reversal_direction=displacement.direction,
            classification=LiquidityContextType.NO_CLEAR_CONTEXT,
            formed_at=displacement.start_time,
            known_at=displacement.known_at,
            liquidity_sequence_id=sequence.id,
            score=0,
            component_scores={},
            features=sequence.soft_feature_values,
            hard_gates=hard_gates,
            failed_hard_gates=failed,
            score_penalties={},
        )
        return context, sequence

    @staticmethod
    def _maximum_consecutive(flags: list[bool]) -> int:
        maximum = current = 0
        for flag in flags:
            current = current + 1 if flag else 0
            maximum = max(maximum, current)
        return maximum

    @staticmethod
    def _signed_break(reference: SwingPoint, attempt: SwingPoint, direction: Direction) -> float:
        if direction == Direction.BEARISH:
            return float(attempt.price - reference.price)
        return float(reference.price - attempt.price)

    @staticmethod
    def _close_beyond(candle: Candle, reference: SwingPoint, direction: Direction) -> bool:
        if direction == Direction.BEARISH:
            return candle.close > reference.price
        return candle.close < reference.price

    @staticmethod
    def _excursion(candle: Candle, reference: SwingPoint, direction: Direction) -> float:
        if direction == Direction.BEARISH:
            return max(0.0, float(candle.high - reference.price))
        return max(0.0, float(reference.price - candle.low))
