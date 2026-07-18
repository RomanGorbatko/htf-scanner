from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from math import isfinite
from uuid import NAMESPACE_URL, UUID, uuid5

from htf_scanner.config import AppConfig
from htf_scanner.data.validation import inspect_candle_quality
from htf_scanner.detectors.displacement import DisplacementDetector
from htf_scanner.detectors.fvg_detector import detect_fvgs
from htf_scanner.detectors.h4_reaction_state_machine import H4ReactionStateMachine
from htf_scanner.domain.candle import Candle
from htf_scanner.domain.displacement import Displacement
from htf_scanner.domain.enums import (
    Direction,
    H4ReactionStatus,
    H4TouchType,
    SetupSide,
    StructureLevelType,
)
from htf_scanner.domain.fvg import FairValueGap
from htf_scanner.domain.reaction import (
    H4MergedCandidate,
    H4Reaction,
    H4ReactionCandidate,
    H4ReactionTransition,
    H4RejectedCandidate,
    H4TouchPhase,
)
from htf_scanner.domain.setup import HTFSetup
from htf_scanner.domain.structure import MarketStructureSnapshot, StructureBreak
from htf_scanner.domain.swing import SwingPoint
from htf_scanner.indicators.candle_features import calculate_candle_features
from htf_scanner.structure.causal_swings import detect_causal_swings
from htf_scanner.structure.market_structure import detect_market_structure


class H4DataQualityError(ValueError):
    pass


@dataclass(frozen=True)
class H4AnalysisResult:
    swings: list[SwingPoint]
    structure_breaks: list[StructureBreak]
    structure_snapshots: list[MarketStructureSnapshot]
    fvgs: list[FairValueGap]
    displacements: list[Displacement]
    touch_phases: list[H4TouchPhase]
    reactions: list[H4Reaction]
    reaction_candidates: list[H4ReactionCandidate]
    rejected_candidates: list[H4RejectedCandidate]
    merged_candidates: list[H4MergedCandidate]
    transitions: list[H4ReactionTransition]
    diagnostics: list[str]


@dataclass
class _PhaseState:
    id: UUID
    first: Candle
    last: Candle
    deepest: Candle
    penetration_price: Decimal
    penetration_fraction: float
    penetration_atr: float
    deepest_price: Decimal
    adverse: Decimal
    close_location: float
    primary_type: H4TouchType
    flags: dict[str, bool]
    bars_from_activation: int
    interaction_indices: list[int] = field(default_factory=list)


def _direction(side: SetupSide) -> Direction:
    return Direction.BULLISH if side == SetupSide.LONG else Direction.BEARISH


class H4ReactionEngine:
    """Incremental state engine for one setup; every update consumes one closed H4 candle."""

    def __init__(
        self,
        setup: HTFSetup,
        zone: FairValueGap,
        config: AppConfig,
        config_hash: str,
    ) -> None:
        if zone.id != setup.fvg_id:
            raise ValueError("reaction zone must be the setup FVG")
        self.setup = setup
        self.zone = zone
        self.config = config
        self.config_hash = config_hash
        self.reaction_id = uuid5(NAMESPACE_URL, f"h4-reaction:{setup.id}")
        self.status = H4ReactionStatus.WAITING_FOR_TOUCH
        self.transitions: list[H4ReactionTransition] = []
        self.candidates: list[H4ReactionCandidate] = []
        self.rejected: list[H4RejectedCandidate] = []
        self._phase_states: list[_PhaseState] = []
        self._pre_mitigation = 0.0
        self._activation_index: int | None = None
        self._post_index = -1
        self._last_touch_index: int | None = None
        self._first_touch: Candle | None = None
        self._first_reaction_at: datetime | None = None
        self._early_components: dict[str, float] = {}
        self._early_score = 0.0
        self._confirmed: H4ReactionCandidate | None = None
        self._confirmed_at: datetime | None = None
        self._invalidated_at: datetime | None = None
        self._expired_at: datetime | None = None
        self._invalidation_reason: str | None = None
        self._pending_beyond_index: int | None = None
        self._closes_beyond = 0
        self._previous: Candle | None = None
        self._last: Candle | None = None
        self._reaction_extreme: Decimal | None = None

    def update(
        self,
        candle: Candle,
        atr: float,
        displacements: list[Displacement],
        breaks_by_id: dict[UUID, StructureBreak],
        fvgs_by_id: dict[UUID, FairValueGap],
    ) -> None:
        if not candle.is_closed:
            return
        self._last = candle
        if candle.close_time <= self.setup.known_at:
            if self._overlaps(candle):
                self._pre_mitigation = max(self._pre_mitigation, self._penetration(candle)[1])
            self._previous = candle
            return
        self._post_index += 1
        if self._activation_index is None:
            self._activation_index = self._post_index
        if self.status in {H4ReactionStatus.INVALIDATED, H4ReactionStatus.EXPIRED}:
            self._previous = candle
            return
        d1_terminal_at = self._d1_terminal_at()
        if d1_terminal_at is not None and d1_terminal_at <= candle.close_time:
            self._terminal(
                H4ReactionStatus.INVALIDATED,
                candle,
                "d1_setup_or_zone_invalidated",
            )
            self._previous = candle
            return
        interaction = self._overlaps(candle) or self._gap_over(candle)
        if interaction:
            phase = self._record_touch(candle, atr)
            if self.status == H4ReactionStatus.WAITING_FOR_TOUCH:
                self._transition(
                    H4ReactionStatus.ZONE_TOUCHED,
                    candle,
                    "first_post_activation_zone_interaction",
                )
            self._update_extreme(candle)
            if self._accepted_beyond(candle, atr):
                self._terminal(H4ReactionStatus.INVALIDATED, candle, "accepted_close_through_zone")
                self._previous = candle
                return
            self._consider_early(candle, atr, phase, displacements, fvgs_by_id)
        else:
            if self._accepted_beyond(candle, atr):
                self._terminal(H4ReactionStatus.INVALIDATED, candle, "accepted_close_through_zone")
                self._previous = candle
                return
            if self._first_touch is not None:
                self._update_extreme(candle)
                phase = self._phase_states[-1]
                self._consider_early(candle, atr, phase, displacements, fvgs_by_id)
        if self._first_touch is not None:
            self._consider_candidates(candle, displacements, breaks_by_id, fvgs_by_id)
        self._consider_expiry(candle)
        self._previous = candle

    def initialize_pre_activation(self, candles: list[Candle]) -> None:
        """Summarize old candles without advancing the post-activation state machine."""
        for candle in sorted(candles, key=lambda item: item.open_time):
            if candle.close_time > self.setup.known_at:
                break
            self._last = candle
            if self._overlaps(candle):
                self._pre_mitigation = max(self._pre_mitigation, self._penetration(candle)[1])
            self._previous = candle

    def export_state(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "transitions": [item.model_dump(mode="json") for item in self.transitions],
            "candidates": [item.model_dump(mode="json") for item in self.candidates],
            "rejected": [item.model_dump(mode="json") for item in self.rejected],
            "phase_states": [self._export_phase(item) for item in self._phase_states],
            "pre_mitigation": self._pre_mitigation,
            "activation_index": self._activation_index,
            "post_index": self._post_index,
            "last_touch_index": self._last_touch_index,
            "first_touch": self._candle_payload(self._first_touch),
            "first_reaction_at": self._iso(self._first_reaction_at),
            "early_components": self._early_components,
            "early_score": self._early_score,
            "confirmed": self._confirmed.model_dump(mode="json") if self._confirmed else None,
            "confirmed_at": self._iso(self._confirmed_at),
            "invalidated_at": self._iso(self._invalidated_at),
            "expired_at": self._iso(self._expired_at),
            "invalidation_reason": self._invalidation_reason,
            "pending_beyond_index": self._pending_beyond_index,
            "closes_beyond": self._closes_beyond,
            "previous": self._candle_payload(self._previous),
            "last": self._candle_payload(self._last),
            "reaction_extreme": (
                str(self._reaction_extreme) if self._reaction_extreme is not None else None
            ),
        }

    def restore_state(self, payload: dict[str, object]) -> None:
        self.status = H4ReactionStatus(str(payload["status"]))
        self.transitions = [
            H4ReactionTransition.model_validate(item) for item in self._list(payload, "transitions")
        ]
        self.candidates = [
            H4ReactionCandidate.model_validate(item) for item in self._list(payload, "candidates")
        ]
        self.rejected = [
            H4RejectedCandidate.model_validate(item) for item in self._list(payload, "rejected")
        ]
        self._phase_states = [
            self._restore_phase(item) for item in self._list(payload, "phase_states")
        ]
        self._pre_mitigation = float(str(payload.get("pre_mitigation", 0.0)))
        self._activation_index = self._optional_int(payload.get("activation_index"))
        self._post_index = int(str(payload.get("post_index", -1)))
        self._last_touch_index = self._optional_int(payload.get("last_touch_index"))
        self._first_touch = self._restore_candle(payload.get("first_touch"))
        self._first_reaction_at = self._restore_time(payload.get("first_reaction_at"))
        raw_components = payload.get("early_components", {})
        if not isinstance(raw_components, dict):
            raise ValueError("H4 early components state must be an object")
        self._early_components = {str(key): float(value) for key, value in raw_components.items()}
        self._early_score = float(str(payload.get("early_score", 0.0)))
        confirmed = payload.get("confirmed")
        self._confirmed = (
            H4ReactionCandidate.model_validate(confirmed) if confirmed is not None else None
        )
        self._confirmed_at = self._restore_time(payload.get("confirmed_at"))
        self._invalidated_at = self._restore_time(payload.get("invalidated_at"))
        self._expired_at = self._restore_time(payload.get("expired_at"))
        reason = payload.get("invalidation_reason")
        self._invalidation_reason = str(reason) if reason is not None else None
        self._pending_beyond_index = self._optional_int(payload.get("pending_beyond_index"))
        self._closes_beyond = int(str(payload.get("closes_beyond", 0)))
        self._previous = self._restore_candle(payload.get("previous"))
        self._last = self._restore_candle(payload.get("last"))
        extreme = payload.get("reaction_extreme")
        self._reaction_extreme = Decimal(str(extreme)) if extreme is not None else None

    @staticmethod
    def _export_phase(phase: _PhaseState) -> dict[str, object]:
        return {
            "id": str(phase.id),
            "first": phase.first.model_dump(mode="json"),
            "last": phase.last.model_dump(mode="json"),
            "deepest": phase.deepest.model_dump(mode="json"),
            "penetration_price": str(phase.penetration_price),
            "penetration_fraction": phase.penetration_fraction,
            "penetration_atr": phase.penetration_atr,
            "deepest_price": str(phase.deepest_price),
            "adverse": str(phase.adverse),
            "close_location": phase.close_location,
            "primary_type": phase.primary_type.value,
            "flags": phase.flags,
            "bars_from_activation": phase.bars_from_activation,
            "interaction_indices": phase.interaction_indices,
        }

    @staticmethod
    def _restore_phase(payload: object) -> _PhaseState:
        if not isinstance(payload, dict):
            raise ValueError("H4 phase state must be an object")
        flags = payload.get("flags", {})
        indices = payload.get("interaction_indices", [])
        if not isinstance(flags, dict) or not isinstance(indices, list):
            raise ValueError("invalid H4 phase state")
        return _PhaseState(
            id=UUID(str(payload["id"])),
            first=Candle.model_validate(payload["first"]),
            last=Candle.model_validate(payload["last"]),
            deepest=Candle.model_validate(payload["deepest"]),
            penetration_price=Decimal(str(payload["penetration_price"])),
            penetration_fraction=float(payload["penetration_fraction"]),
            penetration_atr=float(payload["penetration_atr"]),
            deepest_price=Decimal(str(payload["deepest_price"])),
            adverse=Decimal(str(payload["adverse"])),
            close_location=float(payload["close_location"]),
            primary_type=H4TouchType(str(payload["primary_type"])),
            flags={str(key): bool(value) for key, value in flags.items()},
            bars_from_activation=int(payload["bars_from_activation"]),
            interaction_indices=[int(item) for item in indices],
        )

    @staticmethod
    def _list(payload: dict[str, object], key: str) -> list[object]:
        value = payload.get(key, [])
        if not isinstance(value, list):
            raise ValueError(f"H4 {key} state must be a list")
        return value

    @staticmethod
    def _candle_payload(candle: Candle | None) -> dict[str, object] | None:
        return candle.model_dump(mode="json") if candle else None

    @staticmethod
    def _restore_candle(payload: object) -> Candle | None:
        return Candle.model_validate(payload) if payload is not None else None

    @staticmethod
    def _iso(value: datetime | None) -> str | None:
        return value.isoformat() if value else None

    @staticmethod
    def _restore_time(value: object) -> datetime | None:
        return datetime.fromisoformat(str(value)) if value is not None else None

    @staticmethod
    def _optional_int(value: object) -> int | None:
        return int(str(value)) if value is not None else None

    def _transition(self, target: H4ReactionStatus, candle: Candle, reason: str) -> None:
        transition = H4ReactionStateMachine.transition(
            self.reaction_id,
            self.setup.id,
            self.status,
            target,
            candle.open_time,
            candle.close_time,
            self._post_index,
            reason,
        )
        self.transitions.append(transition)
        self.status = target

    def _terminal(self, target: H4ReactionStatus, candle: Candle, reason: str) -> None:
        self._transition(target, candle, reason)
        if target == H4ReactionStatus.INVALIDATED:
            self._invalidated_at = candle.close_time
            self._invalidation_reason = reason
        else:
            self._expired_at = candle.close_time

    def _d1_terminal_at(self) -> datetime | None:
        times = [
            item
            for item in (self.zone.invalidated_at, self.zone.expired_at)
            if item is not None and item > self.setup.known_at
        ]
        return min(times) if times else None

    def _record_touch(self, candle: Candle, atr: float) -> _PhaseState:
        penetration_price, fraction, deepest_price, adverse, close_location = self._penetration(
            candle
        )
        touch_type, flags = self._touch_type(candle, fraction)
        new_phase = (
            not self._phase_states
            or self._last_touch_index is None
            or self._post_index - self._last_touch_index > self.config.h4_touch.phase_gap_bars + 1
        )
        if new_phase:
            identity = f"h4-touch-phase:{self.setup.id}:{candle.close_time.isoformat()}"
            phase = _PhaseState(
                id=uuid5(NAMESPACE_URL, identity),
                first=candle,
                last=candle,
                deepest=candle,
                penetration_price=penetration_price,
                penetration_fraction=fraction,
                penetration_atr=float(penetration_price) / atr if atr > 0 else 0.0,
                deepest_price=deepest_price,
                adverse=adverse,
                close_location=close_location,
                primary_type=touch_type,
                flags=flags,
                bars_from_activation=self._post_index,
                interaction_indices=[self._post_index],
            )
            self._phase_states.append(phase)
        else:
            phase = self._phase_states[-1]
            phase.last = candle
            phase.interaction_indices.append(self._post_index)
            phase.adverse = max(phase.adverse, adverse)
            phase.flags = {
                key: phase.flags.get(key, False) or value for key, value in flags.items()
            }
            if fraction >= phase.penetration_fraction:
                phase.deepest = candle
                phase.penetration_price = penetration_price
                phase.penetration_fraction = fraction
                phase.penetration_atr = float(penetration_price) / atr if atr > 0 else 0.0
                phase.deepest_price = deepest_price
                phase.close_location = close_location
                phase.primary_type = touch_type
        if self._first_touch is None:
            self._first_touch = candle
        self._last_touch_index = self._post_index
        return phase

    def _overlaps(self, candle: Candle) -> bool:
        return candle.high >= self.zone.lower and candle.low <= self.zone.upper

    def _gap_over(self, candle: Candle) -> bool:
        if self._previous is None:
            return False
        if self.setup.side == SetupSide.SHORT:
            return self._previous.close < self.zone.lower and candle.low > self.zone.upper
        return self._previous.close > self.zone.upper and candle.high < self.zone.lower

    def _penetration(self, candle: Candle) -> tuple[Decimal, float, Decimal, Decimal, float]:
        width = self.zone.upper - self.zone.lower
        if self._gap_over(candle):
            depth = width
        elif self.setup.side == SetupSide.SHORT:
            depth = max(Decimal("0"), min(candle.high, self.zone.upper) - self.zone.lower)
        else:
            depth = max(Decimal("0"), self.zone.upper - max(candle.low, self.zone.lower))
        fraction = min(1.0, max(0.0, float(depth / width)))
        deepest = (
            min(candle.high, self.zone.upper)
            if self.setup.side == SetupSide.SHORT
            else max(candle.low, self.zone.lower)
        )
        adverse = (
            max(Decimal("0"), candle.high - self.zone.upper)
            if self.setup.side == SetupSide.SHORT
            else max(Decimal("0"), self.zone.lower - candle.low)
        )
        close_location = float((candle.close - self.zone.lower) / width)
        return depth, fraction, deepest, adverse, close_location

    def _touch_type(self, candle: Candle, fraction: float) -> tuple[H4TouchType, dict[str, bool]]:
        close_inside = self.zone.lower <= candle.close <= self.zone.upper
        body_low, body_high = min(candle.open, candle.close), max(candle.open, candle.close)
        body_entry = body_high >= self.zone.lower and body_low <= self.zone.upper
        close_through = (
            candle.close > self.zone.upper
            if self.setup.side == SetupSide.SHORT
            else candle.close < self.zone.lower
        )
        flags = {
            "wick_touch": self._overlaps(candle),
            "body_entry": body_entry,
            "close_inside": close_inside,
            "midpoint_reached": fraction >= self.config.h4_touch.midpoint_fraction,
            "full_fill": fraction >= self.config.h4_touch.full_fill_fraction,
            "close_through": close_through,
            "gap_over_zone": self._gap_over(candle),
        }
        priority = (
            (H4TouchType.GAP_OVER_ZONE, "gap_over_zone"),
            (H4TouchType.CLOSE_THROUGH, "close_through"),
            (H4TouchType.FULL_FILL, "full_fill"),
            (H4TouchType.MIDPOINT_REACHED, "midpoint_reached"),
            (H4TouchType.CLOSE_INSIDE, "close_inside"),
            (H4TouchType.BODY_ENTRY, "body_entry"),
            (H4TouchType.WICK_TOUCH, "wick_touch"),
        )
        return next(kind for kind, flag in priority if flags[flag]), flags

    def _consider_early(
        self,
        candle: Candle,
        atr: float,
        phase: _PhaseState,
        displacements: list[Displacement],
        fvgs_by_id: dict[UUID, FairValueGap],
    ) -> None:
        if self.status not in {H4ReactionStatus.ZONE_TOUCHED, H4ReactionStatus.EARLY_REACTION}:
            return
        short = self.setup.side == SetupSide.SHORT
        body = abs(candle.close - candle.open)
        rejection_wick = (
            candle.high - max(candle.open, candle.close)
            if short
            else min(candle.open, candle.close) - candle.low
        )
        close_back = candle.close < self.zone.lower if short else candle.close > self.zone.upper
        rejection = (candle.close < candle.open if short else candle.close > candle.open) and (
            body == 0
            or float(rejection_wick / body) >= self.config.h4_reaction.rejection_wick_body_ratio
        )
        lower_close = False
        local_liquidity = False
        if self._previous is not None and self._previous.close_time > self.setup.known_at:
            lower_close = (
                candle.close < self._previous.close
                if short
                else candle.close > self._previous.close
            )
            local_liquidity = (
                candle.high > self._previous.high and candle.close < self._previous.high
                if short
                else candle.low < self._previous.low and candle.close > self._previous.low
            )
        directional = [
            item for item in displacements if item.direction == _direction(self.setup.side)
        ]
        displacement = bool(directional)
        local_fvg = any(
            item.fvg_id is not None and item.fvg_id in fvgs_by_id for item in directional
        )
        freshness = max(
            0.0,
            1.0
            - phase.bars_from_activation / self.config.h4_reaction.maximum_bars_activation_to_touch,
        )
        components = {
            "touch_quality": self.config.h4_reaction.touch_quality_weight
            * (1.0 - abs(phase.penetration_fraction - 0.5)),
            "close_back": self.config.h4_reaction.close_back_weight if close_back else 0.0,
            "rejection_candle": (
                self.config.h4_reaction.rejection_candle_weight if rejection else 0.0
            ),
            "lower_close": self.config.h4_reaction.lower_close_weight if lower_close else 0.0,
            "local_liquidity": (
                self.config.h4_reaction.local_liquidity_weight if local_liquidity else 0.0
            ),
            "h4_displacement": (
                self.config.h4_reaction.displacement_weight if displacement else 0.0
            ),
            "h4_fvg": self.config.h4_reaction.fvg_weight if local_fvg else 0.0,
            "freshness": self.config.h4_reaction.freshness_weight * freshness,
            "zone_depth_penalty": -self.config.h4_reaction.depth_penalty_weight
            * max(0.0, phase.penetration_fraction - 0.5),
            "dwell_time_penalty": -self.config.h4_reaction.dwell_penalty_per_bar
            * max(0, len(phase.interaction_indices) - 1),
        }
        score = sum(components.values())
        evidence = close_back or rejection or lower_close or displacement
        if evidence and score >= self.config.h4_reaction.minimum_early_score:
            self._early_score = score
            self._early_components = components
            if self.status == H4ReactionStatus.ZONE_TOUCHED:
                self._first_reaction_at = candle.close_time
                self._transition(
                    H4ReactionStatus.EARLY_REACTION,
                    candle,
                    "directional_rejection_evidence",
                )

    def _consider_candidates(
        self,
        candle: Candle,
        displacements: list[Displacement],
        breaks_by_id: dict[UUID, StructureBreak],
        fvgs_by_id: dict[UUID, FairValueGap],
    ) -> None:
        phase = self._phase_states[-1]
        existing = {item.displacement_id for item in self.candidates}
        for displacement in displacements:
            if displacement.id in existing or displacement.direction != _direction(self.setup.side):
                continue
            if displacement.start_time < phase.first.open_time:
                continue
            structure_break = (
                breaks_by_id.get(displacement.structure_break_id)
                if displacement.structure_break_id is not None
                else None
            )
            linked_fvg = (
                fvgs_by_id.get(displacement.fvg_id) if displacement.fvg_id is not None else None
            )
            d1_terminal_at = self._d1_terminal_at()
            gates = {
                "d1_setup_active": d1_terminal_at is None or d1_terminal_at > displacement.known_at,
                "post_touch": displacement.known_at >= phase.first.close_time,
                "direction_match": displacement.direction == _direction(self.setup.side),
                "qualified_displacement": displacement.score
                >= self.config.h4_displacement.minimum_score,
                "linked_structure_break": structure_break is not None,
                "internal_structure_break": structure_break is not None
                and structure_break.level_type == StructureLevelType.INTERNAL,
                "same_impulse": structure_break is not None
                and displacement.start_time <= structure_break.formed_at <= displacement.end_time,
                "linked_h4_fvg": not self.config.h4_reaction.require_h4_fvg
                or linked_fvg is not None,
                "no_accepted_close_through": self.status != H4ReactionStatus.INVALIDATED,
            }
            failed = [key for key, passed in gates.items() if not passed]
            sequence_key = ":".join(
                [
                    str(self.setup.id),
                    str(phase.id),
                    self.setup.side.value,
                    str(structure_break.broken_swing_id) if structure_break else "no-break",
                    str(linked_fvg.id) if linked_fvg else str(displacement.id),
                ]
            )
            identity = f"h4-reaction-candidate:{sequence_key}:{displacement.id}"
            components = {
                **self._early_components,
                "qualified_displacement": displacement.score,
                "internal_structure_break": 1.5 if gates["internal_structure_break"] else 0.0,
                "linked_h4_fvg": 1.0 if linked_fvg is not None else 0.0,
            }
            candidate = H4ReactionCandidate(
                id=uuid5(NAMESPACE_URL, identity),
                sequence_key=sequence_key,
                setup_id=self.setup.id,
                touch_phase_id=phase.id,
                symbol=self.setup.symbol,
                side=self.setup.side,
                displacement_id=displacement.id,
                structure_break_id=structure_break.id if structure_break else None,
                broken_internal_swing_id=(
                    structure_break.broken_swing_id if structure_break else None
                ),
                h4_fvg_id=linked_fvg.id if linked_fvg else None,
                sequence_bars=displacement.sequence_bars,
                known_at=max(
                    displacement.known_at,
                    structure_break.known_at if structure_break else displacement.known_at,
                    linked_fvg.known_at if linked_fvg else displacement.known_at,
                ),
                hard_gates=gates,
                failed_hard_gates=failed,
                score_components=components,
                total_score=sum(components.values()),
            )
            self.candidates.append(candidate)
            if failed:
                rejected_id = uuid5(NAMESPACE_URL, f"h4-rejected:{candidate.id}")
                self.rejected.append(
                    H4RejectedCandidate(
                        id=rejected_id,
                        setup_id=self.setup.id,
                        touch_phase_id=phase.id,
                        known_at=candidate.known_at,
                        reasons=failed,
                        diagnostics={"displacement_score": displacement.score},
                    )
                )
                continue
            if self._confirmed is None:
                self._confirmed = candidate
                self._confirmed_at = candidate.known_at
                if self.status == H4ReactionStatus.ZONE_TOUCHED:
                    self._first_reaction_at = candidate.known_at
                if self.status in {
                    H4ReactionStatus.ZONE_TOUCHED,
                    H4ReactionStatus.EARLY_REACTION,
                }:
                    self._transition(
                        H4ReactionStatus.REACTION_CONFIRMED,
                        candle,
                        "qualified_h4_displacement_with_internal_close_break",
                    )

    def _accepted_beyond(self, candle: Candle, atr: float) -> bool:
        buffer = Decimal(str(self.config.h4_invalidation.boundary_buffer_atr * max(atr, 0.0)))
        beyond = (
            candle.close > self.zone.upper + buffer
            if self.setup.side == SetupSide.SHORT
            else candle.close < self.zone.lower - buffer
        )
        excursion = (
            max(Decimal("0"), candle.close - self.zone.upper)
            if self.setup.side == SetupSide.SHORT
            else max(Decimal("0"), self.zone.lower - candle.close)
        )
        if not beyond:
            self._pending_beyond_index = None
            self._closes_beyond = 0
            return False
        if atr > 0 and float(excursion) / atr >= self.config.h4_invalidation.maximum_excursion_atr:
            return True
        if self._pending_beyond_index is None:
            self._pending_beyond_index = self._post_index
            self._closes_beyond = 1
        else:
            self._closes_beyond += 1
        elapsed = self._post_index - self._pending_beyond_index + 1
        required = max(
            self.config.h4_invalidation.minimum_closes_beyond,
            self.config.h4_invalidation.hold_bars,
            self.config.h4_invalidation.reclaim_window_bars + 1,
        )
        return self._closes_beyond >= self.config.h4_invalidation.minimum_closes_beyond and (
            elapsed >= required
        )

    def _consider_expiry(self, candle: Candle) -> None:
        if self.status in {
            H4ReactionStatus.INVALIDATED,
            H4ReactionStatus.EXPIRED,
            H4ReactionStatus.REACTION_CONFIRMED,
        }:
            return
        total_bars = self._post_index + 1
        if self._first_touch is None:
            if total_bars >= self.config.h4_reaction.maximum_bars_activation_to_touch:
                self._terminal(H4ReactionStatus.EXPIRED, candle, "maximum_bars_before_touch")
            return
        assert self._last_touch_index is not None
        first_touch_index = next(
            phase.interaction_indices[0]
            for phase in self._phase_states
            if phase.first == self._first_touch
        )
        if self._post_index - first_touch_index + 1 >= (
            self.config.h4_reaction.maximum_bars_touch_to_confirmation
        ):
            self._terminal(H4ReactionStatus.EXPIRED, candle, "maximum_bars_touch_to_confirmation")
        elif total_bars >= self.config.h4_reaction.maximum_total_bars:
            self._terminal(H4ReactionStatus.EXPIRED, candle, "maximum_total_reaction_age")

    def _update_extreme(self, candle: Candle) -> None:
        price = candle.high if self.setup.side == SetupSide.LONG else candle.low
        if self._reaction_extreme is None:
            self._reaction_extreme = price
        elif self.setup.side == SetupSide.LONG:
            self._reaction_extreme = max(self._reaction_extreme, price)
        else:
            self._reaction_extreme = min(self._reaction_extreme, price)

    def result(
        self,
    ) -> tuple[
        list[H4TouchPhase],
        H4Reaction | None,
        list[H4ReactionCandidate],
        list[H4RejectedCandidate],
        list[H4MergedCandidate],
        list[H4ReactionTransition],
    ]:
        phases = [self._phase_model(item) for item in self._phase_states]
        canonical, merged = self._canonicalize()
        if canonical is not None:
            self._confirmed = canonical
        if self._first_touch is None and self.status == H4ReactionStatus.WAITING_FOR_TOUCH:
            return phases, None, self.candidates, self.rejected, merged, self.transitions
        anchor = self._first_touch or self._last
        if anchor is None:
            return phases, None, self.candidates, self.rejected, merged, self.transitions
        first_phase = phases[0] if phases else None
        score_components = (
            canonical.score_components if canonical is not None else self._early_components
        )
        known_at = (
            self._invalidated_at
            or self._expired_at
            or self._confirmed_at
            or self._first_reaction_at
            or anchor.close_time
        )
        reaction = H4Reaction(
            id=self.reaction_id,
            setup_id=self.setup.id,
            symbol=self.setup.symbol,
            side=self.setup.side,
            status=self.status,
            zone_id=self.zone.id,
            touch_phase_id=first_phase.id if first_phase else None,
            touch_type=first_phase.primary_touch_type if first_phase else None,
            touch_open_time=self._first_touch.open_time if self._first_touch else None,
            touch_close_time=self._first_touch.close_time if self._first_touch else None,
            formed_at=self._first_touch.open_time if self._first_touch else self.setup.known_at,
            known_at=known_at,
            first_reaction_at=self._first_reaction_at,
            confirmed_at=self._confirmed_at,
            invalidated_at=self._invalidated_at,
            expired_at=self._expired_at,
            entry_price_reference=self.zone.midpoint,
            reaction_extreme_price=self._reaction_extreme,
            penetration_ratio=first_phase.penetration_fraction if first_phase else 0.0,
            reaction_score=sum(score_components.values()),
            score_components=score_components,
            invalidation_reason=self._invalidation_reason,
            displacement_id=canonical.displacement_id if canonical else None,
            structure_break_id=canonical.structure_break_id if canonical else None,
            h4_fvg_id=canonical.h4_fvg_id if canonical else None,
            config_hash=self.config_hash,
            created_at=self.setup.known_at,
            updated_at=known_at,
            features={
                "pre_activation_mitigation_fraction": self._pre_mitigation,
                "touch_phase_count": len(phases),
                "bars_processed_after_activation": self._post_index + 1,
            },
        )
        return phases, reaction, self.candidates, self.rejected, merged, self.transitions

    def _phase_model(self, phase: _PhaseState) -> H4TouchPhase:
        duration = (phase.last.close_time - phase.first.open_time).total_seconds() / 3600
        return H4TouchPhase(
            id=phase.id,
            setup_id=self.setup.id,
            symbol=self.setup.symbol,
            side=self.setup.side,
            first_touch_open_time=phase.first.open_time,
            first_touch_close_time=phase.first.close_time,
            last_touch_close_time=phase.last.close_time,
            deepest_touch_close_time=phase.deepest.close_time,
            deepest_penetration_price=phase.deepest_price,
            penetration_price=phase.penetration_price,
            penetration_fraction=phase.penetration_fraction,
            penetration_atr=phase.penetration_atr,
            maximum_adverse_excursion=phase.adverse,
            close_location=phase.close_location,
            bars_from_activation=phase.bars_from_activation,
            bars_in_zone=len(phase.interaction_indices),
            duration_hours=duration,
            primary_touch_type=phase.primary_type,
            touch_flags=phase.flags,
            pre_activation_mitigation_fraction=self._pre_mitigation,
            post_activation_touch_fraction=phase.penetration_fraction,
            invalidated=self._invalidated_at is not None,
            config_hash=self.config_hash,
        )

    def _canonicalize(self) -> tuple[H4ReactionCandidate | None, list[H4MergedCandidate]]:
        complete = [item for item in self.candidates if not item.failed_hard_gates]
        if not complete:
            return None, []
        ordered = sorted(
            complete,
            key=lambda item: (
                item.known_at,
                -item.total_score,
                item.sequence_bars,
                str(item.id),
            ),
        )
        canonical = ordered[0].model_copy(update={"canonical": True})
        self.candidates = [
            canonical if item.id == canonical.id else item.model_copy(update={"canonical": False})
            for item in self.candidates
        ]
        merged = [
            H4MergedCandidate(
                id=uuid5(NAMESPACE_URL, f"h4-merged:{item.id}:{canonical.id}"),
                setup_id=self.setup.id,
                touch_phase_id=item.touch_phase_id,
                candidate_id=item.id,
                merged_into_candidate_id=canonical.id,
                known_at=item.known_at,
            )
            for item in ordered[1:]
        ]
        return canonical, merged


def detect_h4_reactions(
    candles: list[Candle],
    setups: list[HTFSetup],
    d1_fvgs: list[FairValueGap],
    config: AppConfig,
    config_hash: str,
    *,
    strict_data: bool = False,
) -> H4AnalysisResult:
    quality = inspect_candle_quality(candles, "4h")
    hard_diagnostics = [
        item
        for item in quality.diagnostics
        if item.startswith(
            (
                "MISSING_INTERVAL",
                "DUPLICATE_CANDLE",
                "TIMEFRAME_MISMATCH",
                "INCOMPLETE_CANDLE",
                "NON_UTC_TIMESTAMP",
            )
        )
    ]
    if strict_data and hard_diagnostics:
        raise H4DataQualityError("; ".join(hard_diagnostics))
    ordered = [item for item in quality.ordered if item.is_closed]
    swings = detect_causal_swings(ordered, config.atr.period, config.h4_swing)
    breaks, _promotions, snapshots = detect_market_structure(
        ordered, swings, config.atr.period, config.h4_structure
    )
    h4_fvgs = detect_fvgs(ordered, config.atr.period, config.fvg)
    displacements = DisplacementDetector(config.h4_displacement, config.atr.period).detect(
        ordered, breaks, h4_fvgs
    )
    features = calculate_candle_features(ordered, config.atr.period)
    displacements_by_known: dict[datetime, list[Displacement]] = {}
    for item in displacements:
        displacements_by_known.setdefault(item.known_at, []).append(item)
    breaks_by_id = {item.id: item for item in breaks}
    h4_fvgs_by_id = {item.id: item for item in h4_fvgs}
    d1_fvgs_by_id = {item.id: item for item in d1_fvgs}
    engines = [
        H4ReactionEngine(setup, d1_fvgs_by_id[setup.fvg_id], config, config_hash)
        for setup in sorted(setups, key=lambda item: (item.known_at, str(item.id)))
        if setup.fvg_id in d1_fvgs_by_id
    ]
    for index, candle in enumerate(ordered):
        atr = float(features.iloc[index]["atr"])
        if not isfinite(atr):
            atr = 0.0
        available = displacements_by_known.get(candle.close_time, [])
        for engine in engines:
            engine.update(candle, atr, available, breaks_by_id, h4_fvgs_by_id)
    phases: list[H4TouchPhase] = []
    reactions: list[H4Reaction] = []
    candidates: list[H4ReactionCandidate] = []
    rejected: list[H4RejectedCandidate] = []
    merged: list[H4MergedCandidate] = []
    transitions: list[H4ReactionTransition] = []
    for engine in engines:
        values = engine.result()
        phases.extend(values[0])
        if values[1] is not None:
            reactions.append(values[1])
        candidates.extend(values[2])
        rejected.extend(values[3])
        merged.extend(values[4])
        transitions.extend(values[5])
    return H4AnalysisResult(
        swings=swings,
        structure_breaks=breaks,
        structure_snapshots=snapshots,
        fvgs=h4_fvgs,
        displacements=displacements,
        touch_phases=sorted(phases, key=lambda item: (item.first_touch_close_time, str(item.id))),
        reactions=sorted(
            reactions,
            key=lambda item: (item.known_at or datetime.min.replace(tzinfo=UTC), str(item.id)),
        ),
        reaction_candidates=sorted(candidates, key=lambda item: (item.known_at, str(item.id))),
        rejected_candidates=sorted(rejected, key=lambda item: (item.known_at, str(item.id))),
        merged_candidates=sorted(merged, key=lambda item: (item.known_at, str(item.id))),
        transitions=sorted(transitions, key=lambda item: (item.known_at, str(item.id))),
        diagnostics=quality.diagnostics,
    )
