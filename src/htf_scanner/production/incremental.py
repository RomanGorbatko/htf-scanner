from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from htf_scanner.config import AppConfig
from htf_scanner.detectors.d1_setup_detector import (
    D1AnalysisResult,
    HTFSetupDetector,
    _structure_contexts,
    detect_d1_setups,
)
from htf_scanner.detectors.displacement import DisplacementDetector
from htf_scanner.detectors.h4_reaction_detector import H4AnalysisResult, H4ReactionEngine
from htf_scanner.detectors.incremental_fvg import IncrementalFvgTracker
from htf_scanner.detectors.setup_state_machine import HTFSetupStateMachine
from htf_scanner.domain.candle import Candle
from htf_scanner.domain.displacement import Displacement
from htf_scanner.domain.enums import FvgStatus, H4ReactionStatus, SetupStatus
from htf_scanner.domain.event import SetupEvent
from htf_scanner.domain.fvg import FairValueGap
from htf_scanner.domain.liquidity import LiquidityContext, LiquidityInteraction, LiquiditySequence
from htf_scanner.domain.production import ProductionEventType, ScannerEvent
from htf_scanner.domain.reaction import (
    H4MergedCandidate,
    H4Reaction,
    H4ReactionCandidate,
    H4ReactionTransition,
    H4RejectedCandidate,
    H4TouchPhase,
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
from htf_scanner.indicators.incremental_atr import WilderAtrState
from htf_scanner.structure.causal_swings import CausalSwingDetector
from htf_scanner.structure.liquidity_context import LiquidityContextClassifier
from htf_scanner.structure.liquidity_interactions import (
    LiquidityInteractionTracker,
    _external_swings,
)
from htf_scanner.structure.market_structure import MarketStructureEngine


@dataclass(frozen=True)
class IncrementalUpdate:
    d1: D1AnalysisResult
    h4: H4AnalysisResult
    events: list[ScannerEvent]
    new_d1_candles: int
    new_h4_candles: int
    rebuilt: bool


@dataclass
class _PrimitiveState:
    candles: list[Candle]
    atr_values: list[float]
    atr: WilderAtrState
    swing_engine: CausalSwingDetector
    structure_engine: MarketStructureEngine
    fvg_tracker: IncrementalFvgTracker
    displacement_detector: DisplacementDetector
    liquidity_tracker: LiquidityInteractionTracker | None
    swings: list[SwingPoint]
    breaks: list[StructureBreak]
    promotions: list[StructurePromotion]
    snapshots: list[MarketStructureSnapshot]
    displacements: list[Displacement]
    interactions: list[LiquidityInteraction]

    def update(self, candle: Candle) -> list[Displacement]:
        if not candle.is_closed:
            raise ValueError("incremental detector accepts closed candles only")
        if self.candles and candle.open_time <= self.candles[-1].open_time:
            raise ValueError("incremental candles must be strictly ordered and new")
        atr = self.atr.update(candle)
        if not isfinite(atr):
            atr = 0.0
        before = self.snapshots[-1] if self.snapshots else None
        self.candles.append(candle)
        self.atr_values.append(atr)
        self.fvg_tracker.update(self.candles, atr)
        swing = self.swing_engine.update(candle, atr)
        new_swings = [swing] if swing is not None else []
        self.swings.extend(new_swings)
        breaks, promotions, snapshot = self.structure_engine.update(candle, atr, new_swings)
        self.breaks.extend(breaks)
        self.promotions.extend(promotions)
        self.snapshots.append(snapshot)
        if self.liquidity_tracker is not None:
            swings_by_id = {item.id: item for item in self.swings}
            self.interactions.extend(
                self.liquidity_tracker.update(
                    candle,
                    atr,
                    len(self.candles) - 1,
                    _external_swings(before, swings_by_id),
                    _external_swings(snapshot, swings_by_id),
                )
            )
        new_displacements = self.displacement_detector.detect_ending_at(
            self.candles,
            len(self.candles) - 1,
            atr,
            self.breaks,
            self.fvg_tracker.fvgs,
        )
        self.displacements.extend(new_displacements)
        return new_displacements

    def export(self) -> dict[str, object]:
        return {
            "candles": [item.model_dump(mode="json") for item in self.candles],
            "atr_values": self.atr_values,
            "atr": self.atr.snapshot(),
            "swing_engine": self.swing_engine.export_state(),
            "structure_engine": self.structure_engine.export_state(),
            "fvg_tracker": self.fvg_tracker.export_state(),
            "liquidity_tracker": (
                self.liquidity_tracker.export_state() if self.liquidity_tracker else None
            ),
            "swings": _dump(self.swings),
            "breaks": _dump(self.breaks),
            "promotions": _dump(self.promotions),
            "snapshots": _dump(self.snapshots),
            "displacements": _dump(self.displacements),
            "interactions": _dump(self.interactions),
        }


class CausalIncrementalBackend:
    """Persistable D1/H4 engine that only evaluates appended candles after bootstrap."""

    def __init__(self, config: AppConfig, config_hash: str) -> None:
        self.config = config
        self.config_hash = config_hash
        self.d1 = self._empty_primitive("d1")
        self.h4 = self._empty_primitive("4h")
        self.d1_result = _empty_d1()
        self.h4_result = _empty_h4()
        self.reaction_engines: dict[UUID, H4ReactionEngine] = {}
        self.initialized_at = datetime.now(UTC)

    def bootstrap(self, d1_candles: list[Candle], h4_candles: list[Candle]) -> IncrementalUpdate:
        self.d1 = self._empty_primitive("d1")
        self.h4 = self._empty_primitive("4h")
        for candle in sorted(d1_candles, key=lambda item: item.open_time):
            self.d1.update(candle)
        for candle in sorted(h4_candles, key=lambda item: item.open_time):
            self.h4.update(candle)
        self.d1_result = detect_d1_setups(self.d1.candles, self.config, self.config_hash)
        self._build_reaction_engines()
        self.h4_result = self._collect_h4()
        self.initialized_at = datetime.now(UTC)
        events = self._historical_events()
        return IncrementalUpdate(
            d1=self.d1_result,
            h4=self.h4_result,
            events=events,
            new_d1_candles=len(d1_candles),
            new_h4_candles=len(h4_candles),
            rebuilt=True,
        )

    def update(
        self, new_d1_candles: list[Candle], new_h4_candles: list[Candle]
    ) -> IncrementalUpdate:
        events: list[ScannerEvent] = []
        for candle in sorted(new_d1_candles, key=lambda item: item.open_time):
            events.extend(self._update_d1(candle))
        self._sync_reaction_engines()
        for candle in sorted(new_h4_candles, key=lambda item: item.open_time):
            events.extend(self._update_h4(candle))
        self.h4_result = self._collect_h4()
        return IncrementalUpdate(
            d1=self.d1_result,
            h4=self.h4_result,
            events=events,
            new_d1_candles=len(new_d1_candles),
            new_h4_candles=len(new_h4_candles),
            rebuilt=False,
        )

    def _update_d1(self, candle: Candle) -> list[ScannerEvent]:
        old_setups = {item.id: item for item in self.d1_result.setups}
        new_displacements = self.d1.update(candle)
        explicit = _structure_contexts(
            self.d1.swings,
            self.d1.breaks,
            self.d1.promotions,
            self.d1.snapshots,
        )
        classifier = LiquidityContextClassifier(
            self.d1.candles,
            self.config.atr.period,
            self.config.liquidity,
            self.d1.interactions,
            self.d1.atr_values,
        )
        classified = [
            classifier.classify_with_sequence(
                displacement,
                explicit.get(displacement.structure_break_id)
                if displacement.structure_break_id
                else None,
            )
            for displacement in new_displacements
        ]
        new_contexts = [item[0] for item in classified]
        new_sequences = [item[1] for item in classified]
        created, candidates, merged, transitions, rejected, setup_events = HTFSetupDetector(
            self.config, self.config_hash
        ).detect(
            self.d1.candles,
            self.d1.fvg_tracker.fvgs,
            self.d1.swings,
            self.d1.breaks,
            new_displacements,
            new_contexts,
        )
        setups, terminal_transitions = self._advance_setups(
            list(old_setups.values()) + created,
            len(self.d1.candles) - 1,
            candle,
        )
        all_transitions = self.d1_result.setup_transitions + transitions + terminal_transitions
        self.d1_result = D1AnalysisResult(
            fvgs=self.d1.fvg_tracker.fvgs,
            swings=self.d1.swings,
            structure_breaks=self.d1.breaks,
            structure_promotions=self.d1.promotions,
            structure_snapshots=self.d1.snapshots,
            displacements=self.d1.displacements,
            liquidity_interactions=self.d1.interactions,
            liquidity_contexts=self.d1_result.liquidity_contexts + new_contexts,
            liquidity_sequences=self.d1_result.liquidity_sequences + new_sequences,
            setup_candidates=self.d1_result.setup_candidates + candidates,
            merged_candidates=self.d1_result.merged_candidates + merged,
            setups=sorted(_unique_models(setups), key=lambda item: (item.known_at, str(item.id))),
            setup_transitions=_unique_models(all_transitions),
            rejected_candidates=self.d1_result.rejected_candidates + rejected,
            events=self.d1_result.events + setup_events,
        )
        production = [self._setup_active_event(item) for item in created]
        production.extend(self._setup_terminal_event(item) for item in terminal_transitions)
        return production

    def _advance_setups(
        self, setups: list[HTFSetup], bar_index: int, candle: Candle
    ) -> tuple[list[HTFSetup], list[HTFSetupTransition]]:
        fvgs = {item.id: item for item in self.d1.fvg_tracker.fvgs}
        state_machine = HTFSetupStateMachine()
        updated: list[HTFSetup] = []
        transitions: list[HTFSetupTransition] = []
        for setup in _unique_models(setups):
            if setup.status != SetupStatus.ACTIVE:
                updated.append(setup)
                continue
            fvg = fvgs[setup.fvg_id]
            transition: HTFSetupTransition | None
            if fvg.status in {FvgStatus.INVALIDATED, FvgStatus.FULLY_FILLED}:
                changed, transition = state_machine.transition(
                    setup,
                    SetupStatus.INVALIDATED,
                    candle.close_time,
                    bar_index,
                    "fvg_invalidated"
                    if fvg.status == FvgStatus.INVALIDATED
                    else "fvg_fully_filled",
                )
            else:
                changed, transition = state_machine.expire_if_due(
                    setup, candle.close_time, bar_index
                )
            updated.append(changed)
            if transition is not None:
                transitions.append(transition)
        return updated, transitions

    def _update_h4(self, candle: Candle) -> list[ScannerEvent]:
        before = {
            (setup_id, item.id): item
            for setup_id, engine in self.reaction_engines.items()
            for item in engine.transitions
        }
        new_displacements = self.h4.update(candle)
        breaks_by_id = {item.id: item for item in self.h4.breaks}
        fvgs_by_id = {item.id: item for item in self.h4.fvg_tracker.fvgs}
        for engine in self.reaction_engines.values():
            engine.update(
                candle,
                self.h4.atr_values[-1],
                new_displacements,
                breaks_by_id,
                fvgs_by_id,
            )
        result: list[ScannerEvent] = []
        for setup_id, engine in self.reaction_engines.items():
            for transition in engine.transitions:
                if (setup_id, transition.id) not in before:
                    event_type = _reaction_event_type(transition.to_status)
                    if event_type is not None:
                        result.append(
                            self._event(
                                event_type,
                                setup_id,
                                engine.setup.symbol,
                                engine.setup.side,
                                transition.formed_at,
                                transition.known_at,
                                transition.id,
                                {"reason": transition.reason},
                            )
                        )
        return result

    def _build_reaction_engines(self) -> None:
        self.reaction_engines = {}
        self._sync_reaction_engines(replay_existing=True)

    def _sync_reaction_engines(self, *, replay_existing: bool = False) -> None:
        d1_fvgs = {item.id: item for item in self.d1_result.fvgs}
        for setup in self.d1_result.setups:
            zone = d1_fvgs.get(setup.fvg_id)
            if zone is None:
                continue
            engine = self.reaction_engines.get(setup.id)
            if engine is None:
                engine = H4ReactionEngine(setup, zone, self.config, self.config_hash)
                self.reaction_engines[setup.id] = engine
                if replay_existing:
                    self._replay_engine(engine)
                else:
                    engine.initialize_pre_activation(self.h4.candles)
            else:
                engine.setup = setup
                engine.zone = zone

    def _replay_engine(self, engine: H4ReactionEngine) -> None:
        breaks_by_id = {item.id: item for item in self.h4.breaks}
        fvgs_by_id = {item.id: item for item in self.h4.fvg_tracker.fvgs}
        by_known: dict[datetime, list[Displacement]] = {}
        for displacement in self.h4.displacements:
            by_known.setdefault(displacement.known_at, []).append(displacement)
        for index, candle in enumerate(self.h4.candles):
            engine.update(
                candle,
                self.h4.atr_values[index],
                by_known.get(candle.close_time, []),
                breaks_by_id,
                fvgs_by_id,
            )

    def _collect_h4(self) -> H4AnalysisResult:
        phases: list[H4TouchPhase] = []
        reactions: list[H4Reaction] = []
        candidates: list[H4ReactionCandidate] = []
        rejected: list[H4RejectedCandidate] = []
        merged: list[H4MergedCandidate] = []
        transitions: list[H4ReactionTransition] = []
        for engine in self.reaction_engines.values():
            (
                engine_phases,
                reaction,
                engine_candidates,
                engine_rejected,
                engine_merged,
                engine_transitions,
            ) = engine.result()
            phases.extend(engine_phases)
            if reaction is not None:
                reactions.append(reaction)
            candidates.extend(engine_candidates)
            rejected.extend(engine_rejected)
            merged.extend(engine_merged)
            transitions.extend(engine_transitions)
        return H4AnalysisResult(
            swings=self.h4.swings,
            structure_breaks=self.h4.breaks,
            structure_snapshots=self.h4.snapshots,
            fvgs=self.h4.fvg_tracker.fvgs,
            displacements=self.h4.displacements,
            touch_phases=phases,
            reactions=reactions,
            reaction_candidates=candidates,
            rejected_candidates=rejected,
            merged_candidates=merged,
            transitions=transitions,
            diagnostics=[],
        )

    def export_state(self) -> dict[str, object]:
        return {
            "initialized_at": self.initialized_at.isoformat(),
            "d1": self.d1.export(),
            "h4": self.h4.export(),
            "d1_result": _dump_d1(self.d1_result),
            "reaction_engines": {
                str(setup_id): engine.export_state()
                for setup_id, engine in self.reaction_engines.items()
            },
        }

    @classmethod
    def restore(
        cls, config: AppConfig, config_hash: str, payload: dict[str, Any]
    ) -> "CausalIncrementalBackend":
        backend = cls(config, config_hash)
        backend.initialized_at = datetime.fromisoformat(str(payload["initialized_at"]))
        backend.d1 = backend._restore_primitive(_object(payload, "d1"), "d1")
        backend.h4 = backend._restore_primitive(_object(payload, "h4"), "4h")
        backend.d1_result = _restore_d1(_object(payload, "d1_result"))
        raw_engines = _object(payload, "reaction_engines")
        fvgs = {item.id: item for item in backend.d1_result.fvgs}
        setups = {item.id: item for item in backend.d1_result.setups}
        for raw_id, state in raw_engines.items():
            setup_id = UUID(str(raw_id))
            setup = setups[setup_id]
            engine = H4ReactionEngine(setup, fvgs[setup.fvg_id], config, config_hash)
            if not isinstance(state, dict):
                raise ValueError("reaction engine state must be an object")
            engine.restore_state(state)
            backend.reaction_engines[setup_id] = engine
        backend.h4_result = backend._collect_h4()
        return backend

    def _empty_primitive(self, timeframe: str) -> _PrimitiveState:
        is_d1 = timeframe == "d1"
        swing_config = self.config.swings if is_d1 else self.config.h4_swing
        structure_config = self.config.structure if is_d1 else self.config.h4_structure
        displacement_config = self.config.displacement if is_d1 else self.config.h4_displacement
        return _PrimitiveState(
            candles=[],
            atr_values=[],
            atr=WilderAtrState(self.config.atr.period),
            swing_engine=CausalSwingDetector(swing_config),
            structure_engine=MarketStructureEngine(structure_config),
            fvg_tracker=IncrementalFvgTracker.empty(self.config.fvg),
            displacement_detector=DisplacementDetector(displacement_config, self.config.atr.period),
            liquidity_tracker=(
                LiquidityInteractionTracker(self.config.liquidity) if is_d1 else None
            ),
            swings=[],
            breaks=[],
            promotions=[],
            snapshots=[],
            displacements=[],
            interactions=[],
        )

    def _restore_primitive(self, payload: dict[str, Any], timeframe: str) -> _PrimitiveState:
        state = self._empty_primitive(timeframe)
        state.candles = _models(payload, "candles", Candle)
        state.atr_values = [float(item) for item in _array(payload, "atr_values")]
        state.atr = WilderAtrState.restore(_object(payload, "atr"))
        state.swing_engine.restore_state(_object(payload, "swing_engine"))
        state.structure_engine.restore_state(_object(payload, "structure_engine"))
        state.fvg_tracker.restore_state(_object(payload, "fvg_tracker"))
        liquidity = payload.get("liquidity_tracker")
        if state.liquidity_tracker is not None and isinstance(liquidity, dict):
            state.liquidity_tracker.restore_state(liquidity)
        state.swings = _models(payload, "swings", SwingPoint)
        state.breaks = _models(payload, "breaks", StructureBreak)
        state.promotions = _models(payload, "promotions", StructurePromotion)
        state.snapshots = _models(payload, "snapshots", MarketStructureSnapshot)
        state.displacements = _models(payload, "displacements", Displacement)
        state.interactions = _models(payload, "interactions", LiquidityInteraction)
        return state

    def _setup_active_event(self, setup: HTFSetup) -> ScannerEvent:
        return self._event(
            ProductionEventType.D1_SETUP_ACTIVE,
            setup.id,
            setup.symbol,
            setup.side,
            setup.formed_at,
            setup.known_at,
            None,
            {
                "quality_score": setup.quality_score,
                "context": setup.liquidity_classification.value,
                "fvg_id": str(setup.fvg_id),
                "invalidation_price": str(setup.invalidation_price),
                "current_status": setup.status.value,
            },
        )

    def _setup_terminal_event(self, transition: HTFSetupTransition) -> ScannerEvent:
        setup = next(item for item in self.d1_result.setups if item.id == transition.setup_id)
        return self._event(
            ProductionEventType.D1_SETUP_INVALIDATED,
            setup.id,
            setup.symbol,
            setup.side,
            transition.known_at,
            transition.known_at,
            transition.id,
            {"reason": transition.reason},
        )

    def _historical_events(self) -> list[ScannerEvent]:
        events = [self._setup_active_event(setup) for setup in self.d1_result.setups]
        events.extend(
            self._setup_terminal_event(transition)
            for transition in self.d1_result.setup_transitions
            if transition.to_status in {SetupStatus.INVALIDATED, SetupStatus.EXPIRED}
        )
        setups = {item.id: item for item in self.d1_result.setups}
        for transition in self.h4_result.transitions:
            event_type = _reaction_event_type(transition.to_status)
            setup = setups.get(transition.setup_id)
            if event_type is None or setup is None:
                continue
            events.append(
                self._event(
                    event_type,
                    setup.id,
                    setup.symbol,
                    setup.side,
                    transition.formed_at,
                    transition.known_at,
                    transition.id,
                    {"reason": transition.reason, "historical": True},
                )
            )
        return sorted(events, key=lambda item: (item.known_at, item.event_type.value, str(item.id)))

    def _event(
        self,
        event_type: ProductionEventType,
        entity_id: UUID,
        symbol: str,
        side: Any,
        formed_at: datetime,
        known_at: datetime,
        transition_id: UUID | None,
        payload: dict[str, Any],
    ) -> ScannerEvent:
        identity = ":".join(
            [
                event_type.value,
                str(entity_id),
                str(transition_id or known_at.isoformat()),
                self.config_hash,
            ]
        )
        return ScannerEvent(
            id=uuid5(NAMESPACE_URL, identity),
            event_type=event_type,
            entity_id=entity_id,
            transition_id=transition_id,
            symbol=symbol,
            side=side,
            formed_at=formed_at,
            known_at=known_at,
            config_hash=self.config_hash,
            payload=payload,
        )


def _reaction_event_type(status: H4ReactionStatus) -> ProductionEventType | None:
    return {
        H4ReactionStatus.ZONE_TOUCHED: ProductionEventType.H4_ZONE_TOUCHED,
        H4ReactionStatus.EARLY_REACTION: ProductionEventType.H4_EARLY_REACTION,
        H4ReactionStatus.REACTION_CONFIRMED: ProductionEventType.H4_REACTION_CONFIRMED,
        H4ReactionStatus.INVALIDATED: ProductionEventType.H4_REACTION_INVALIDATED,
        H4ReactionStatus.EXPIRED: ProductionEventType.H4_REACTION_EXPIRED,
    }.get(status)


def _dump(items: list[Any]) -> list[dict[str, Any]]:
    return [item.model_dump(mode="json") for item in items]


def _unique_models(items: list[Any]) -> list[Any]:
    return list({item.id: item for item in items}.values())


def _empty_d1() -> D1AnalysisResult:
    return D1AnalysisResult([], [], [], [], [], [], [], [], [], [], [], [], [], [], [])


def _empty_h4() -> H4AnalysisResult:
    return H4AnalysisResult([], [], [], [], [], [], [], [], [], [], [], [])


def _dump_d1(result: D1AnalysisResult) -> dict[str, object]:
    return {
        "fvgs": _dump(result.fvgs),
        "swings": _dump(result.swings),
        "structure_breaks": _dump(result.structure_breaks),
        "structure_promotions": _dump(result.structure_promotions),
        "structure_snapshots": _dump(result.structure_snapshots),
        "displacements": _dump(result.displacements),
        "liquidity_interactions": _dump(result.liquidity_interactions),
        "liquidity_contexts": _dump(result.liquidity_contexts),
        "liquidity_sequences": _dump(result.liquidity_sequences),
        "setup_candidates": _dump(result.setup_candidates),
        "merged_candidates": _dump(result.merged_candidates),
        "setups": _dump(result.setups),
        "setup_transitions": _dump(result.setup_transitions),
        "rejected_candidates": _dump(result.rejected_candidates),
        "events": _dump(result.events),
    }


def _restore_d1(payload: dict[str, Any]) -> D1AnalysisResult:
    return D1AnalysisResult(
        fvgs=_models(payload, "fvgs", FairValueGap),
        swings=_models(payload, "swings", SwingPoint),
        structure_breaks=_models(payload, "structure_breaks", StructureBreak),
        structure_promotions=_models(payload, "structure_promotions", StructurePromotion),
        structure_snapshots=_models(payload, "structure_snapshots", MarketStructureSnapshot),
        displacements=_models(payload, "displacements", Displacement),
        liquidity_interactions=_models(payload, "liquidity_interactions", LiquidityInteraction),
        liquidity_contexts=_models(payload, "liquidity_contexts", LiquidityContext),
        liquidity_sequences=_models(payload, "liquidity_sequences", LiquiditySequence),
        setup_candidates=_models(payload, "setup_candidates", D1SetupCandidate),
        merged_candidates=_models(payload, "merged_candidates", MergedSetupCandidate),
        setups=_models(payload, "setups", HTFSetup),
        setup_transitions=_models(payload, "setup_transitions", HTFSetupTransition),
        rejected_candidates=_models(payload, "rejected_candidates", RejectedSetupCandidate),
        events=_models(payload, "events", SetupEvent),
    )


def _models(payload: dict[str, Any], key: str, model: Any) -> list[Any]:
    return [model.model_validate(item) for item in _array(payload, key)]


def _array(payload: dict[str, Any], key: str) -> list[Any]:
    value = payload.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"checkpoint {key} must be a list")
    return value


def _object(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"checkpoint {key} must be an object")
    return value
