from typing import Any

from sqlalchemy import Engine
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from htf_scanner.domain.displacement import Displacement
from htf_scanner.domain.event import SetupEvent
from htf_scanner.domain.fvg import FairValueGap
from htf_scanner.domain.liquidity import (
    LiquidityContext,
    LiquidityInteraction,
    LiquiditySequence,
)
from htf_scanner.domain.outcome import ReactionOutcome, ReactionTargetOutcome, SetupOutcome
from htf_scanner.domain.reaction import (
    H4MergedCandidate,
    H4Reaction,
    H4ReactionCandidate,
    H4ReactionTransition,
    H4TouchPhase,
)
from htf_scanner.domain.run import BatchRun, BatchSymbolRun, ScannerRun
from htf_scanner.domain.setup import (
    D1SetupCandidate,
    HTFSetup,
    HTFSetupTransition,
    MergedSetupCandidate,
    RejectedSetupCandidate,
)
from htf_scanner.domain.structure import StructureBreak, StructurePromotion
from htf_scanner.domain.swing import SwingPoint
from htf_scanner.storage.models import (
    Base,
    BatchRunRow,
    BatchSymbolRunRow,
    D1SetupCandidateRow,
    DisplacementRow,
    FvgRow,
    H4MergedCandidateRow,
    H4ReactionCandidateRow,
    H4ReactionRow,
    H4ReactionTransitionRow,
    H4TouchPhaseRow,
    HTFSetupRow,
    HTFSetupTransitionRow,
    LiquidityContextRow,
    LiquidityInteractionRow,
    LiquiditySequenceRow,
    MergedSetupCandidateRow,
    ReactionOutcomeRow,
    ReactionTargetOutcomeRow,
    RejectedSetupCandidateRow,
    ScannerRunRow,
    SetupEventRow,
    SetupOutcomeRow,
    StructureBreakRow,
    StructurePromotionRow,
    SwingRow,
)

MarketArtifact = (
    FairValueGap
    | SwingPoint
    | StructureBreak
    | Displacement
    | LiquidityContext
    | LiquidityInteraction
    | LiquiditySequence
    | HTFSetup
)


class AnalysisRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def upsert_fvgs(self, items: list[FairValueGap]) -> int:
        return self._upsert(
            FvgRow,
            [self._market_record(item, item.formed_at) for item in items],
        )

    def upsert_swings(self, items: list[SwingPoint]) -> int:
        return self._upsert(
            SwingRow,
            [self._market_record(item, item.formed_at) for item in items],
        )

    def upsert_structure_breaks(self, items: list[StructureBreak]) -> int:
        return self._upsert(
            StructureBreakRow,
            [self._market_record(item, item.formed_at) for item in items],
        )

    def upsert_structure_promotions(self, items: list[StructurePromotion]) -> int:
        records = [
            {
                "id": str(item.id),
                "symbol": item.symbol,
                "timeframe": item.timeframe,
                "promoted_at": item.promoted_at,
                "payload": item.model_dump(mode="json"),
            }
            for item in items
        ]
        return self._upsert(StructurePromotionRow, records)

    def upsert_displacements(self, items: list[Displacement]) -> int:
        return self._upsert(
            DisplacementRow,
            [self._market_record(item, item.start_time) for item in items],
        )

    def upsert_liquidity_contexts(self, items: list[LiquidityContext]) -> int:
        return self._upsert(
            LiquidityContextRow,
            [self._market_record(item, item.formed_at) for item in items],
        )

    def upsert_liquidity_interactions(self, items: list[LiquidityInteraction]) -> int:
        records = [
            {
                **self._market_record(item, item.formed_at),
                "external_level_id": str(item.external_level_id),
            }
            for item in items
        ]
        return self._upsert(LiquidityInteractionRow, records)

    def upsert_liquidity_sequences(self, items: list[LiquiditySequence]) -> int:
        return self._upsert(
            LiquiditySequenceRow,
            [self._market_record(item, item.formed_at) for item in items],
        )

    def upsert_setups(self, items: list[HTFSetup]) -> int:
        records = [
            {**self._market_record(item, item.formed_at), "fvg_id": str(item.fvg_id)}
            for item in items
        ]
        return self._upsert(HTFSetupRow, records)

    def upsert_setup_transitions(self, items: list[HTFSetupTransition]) -> int:
        records = [
            {
                "id": str(item.id),
                "setup_id": str(item.setup_id),
                "known_at": item.known_at,
                "payload": item.model_dump(mode="json"),
            }
            for item in items
        ]
        return self._upsert(HTFSetupTransitionRow, records)

    def upsert_rejected_candidates(self, items: list[RejectedSetupCandidate]) -> int:
        records = [
            {
                "id": str(item.id),
                "symbol": item.symbol,
                "timeframe": item.timeframe,
                "rejected_at": item.rejected_at,
                "payload": item.model_dump(mode="json"),
            }
            for item in items
        ]
        return self._upsert(RejectedSetupCandidateRow, records)

    def upsert_setup_candidates(self, items: list[D1SetupCandidate]) -> int:
        records = [
            {
                "id": str(item.id),
                "symbol": item.symbol,
                "timeframe": item.timeframe,
                "known_at": item.known_at,
                "payload": item.model_dump(mode="json"),
            }
            for item in items
        ]
        return self._upsert(D1SetupCandidateRow, records)

    def upsert_merged_candidates(self, items: list[MergedSetupCandidate]) -> int:
        records = [
            {
                "id": str(item.id),
                "symbol": item.symbol,
                "timeframe": item.timeframe,
                "known_at": item.known_at,
                "payload": item.model_dump(mode="json"),
            }
            for item in items
        ]
        return self._upsert(MergedSetupCandidateRow, records)

    def upsert_reactions(self, items: list[H4Reaction], run_id: str = "") -> int:
        records = [
            {
                "id": str(item.id),
                "setup_id": str(item.setup_id),
                "known_at": item.known_at,
                "payload": {
                    **item.model_dump(mode="json"),
                    **({"scanner_run_id": run_id} if run_id else {}),
                },
            }
            for item in items
        ]
        return self._upsert(H4ReactionRow, records)

    def upsert_h4_touch_phases(self, items: list[H4TouchPhase], run_id: str = "") -> int:
        return self._upsert(
            H4TouchPhaseRow,
            [
                {
                    "id": str(item.id),
                    "setup_id": str(item.setup_id),
                    "run_id": run_id,
                    "known_at": item.first_touch_close_time,
                    "payload": item.model_dump(mode="json"),
                }
                for item in items
            ],
        )

    def upsert_h4_candidates(self, items: list[H4ReactionCandidate], run_id: str = "") -> int:
        return self._upsert(
            H4ReactionCandidateRow,
            [
                {
                    "id": str(item.id),
                    "setup_id": str(item.setup_id),
                    "run_id": run_id,
                    "known_at": item.known_at,
                    "payload": item.model_dump(mode="json"),
                }
                for item in items
            ],
        )

    def upsert_h4_merged_candidates(self, items: list[H4MergedCandidate], run_id: str = "") -> int:
        return self._upsert(
            H4MergedCandidateRow,
            [
                {
                    "id": str(item.id),
                    "setup_id": str(item.setup_id),
                    "run_id": run_id,
                    "known_at": item.known_at,
                    "payload": item.model_dump(mode="json"),
                }
                for item in items
            ],
        )

    def upsert_h4_transitions(self, items: list[H4ReactionTransition], run_id: str = "") -> int:
        return self._upsert(
            H4ReactionTransitionRow,
            [
                {
                    "id": str(item.id),
                    "reaction_id": str(item.reaction_id),
                    "run_id": run_id,
                    "known_at": item.known_at,
                    "payload": item.model_dump(mode="json"),
                }
                for item in items
            ],
        )

    def upsert_reaction_outcomes(self, items: list[ReactionOutcome], run_id: str = "") -> int:
        return self._upsert(
            ReactionOutcomeRow,
            [
                {
                    "id": str(item.id),
                    "reaction_id": str(item.reaction_id),
                    "run_id": run_id,
                    "horizon_bars": item.horizon_bars,
                    "known_at": item.evaluated_at,
                    "payload": item.model_dump(mode="json"),
                }
                for item in items
            ],
        )

    def upsert_reaction_target_outcomes(
        self, items: list[ReactionTargetOutcome], run_id: str = ""
    ) -> int:
        return self._upsert(
            ReactionTargetOutcomeRow,
            [
                {
                    "id": str(item.id),
                    "reaction_id": str(item.reaction_id),
                    "run_id": run_id,
                    "known_at": item.known_at,
                    "payload": item.model_dump(mode="json"),
                }
                for item in items
            ],
        )

    def upsert_batch_runs(self, items: list[BatchRun]) -> int:
        return self._upsert(
            BatchRunRow,
            [
                {
                    "id": str(item.id),
                    "config_hash": item.config_hash,
                    "started_at": item.started_at,
                    "status": item.status.value,
                    "payload": item.model_dump(mode="json"),
                }
                for item in items
            ],
        )

    def upsert_batch_symbol_runs(self, items: list[BatchSymbolRun]) -> int:
        return self._upsert(
            BatchSymbolRunRow,
            [
                {
                    "id": str(item.id),
                    "batch_run_id": str(item.batch_run_id),
                    "symbol": item.symbol,
                    "status": item.status.value,
                    "payload": item.model_dump(mode="json"),
                }
                for item in items
            ],
        )

    def upsert_outcomes(self, items: list[SetupOutcome]) -> int:
        records = [
            {
                "id": str(item.id),
                "setup_id": str(item.setup_id),
                "known_at": item.evaluated_at,
                "payload": item.model_dump(mode="json"),
            }
            for item in items
        ]
        return self._upsert(SetupOutcomeRow, records)

    def upsert_events(self, items: list[SetupEvent]) -> int:
        records = [
            {
                "id": str(item.id),
                "setup_id": str(item.setup_id),
                "known_at": item.known_at,
                "payload": item.model_dump(mode="json"),
            }
            for item in items
        ]
        return self._upsert(SetupEventRow, records)

    def upsert_runs(self, items: list[ScannerRun]) -> int:
        records = [
            {
                "id": str(item.id),
                "config_hash": item.config_hash,
                "symbol": item.symbol,
                "started_at": item.started_at,
                "status": item.status.value,
                "payload": item.model_dump(mode="json"),
            }
            for item in items
        ]
        return self._upsert(ScannerRunRow, records)

    @staticmethod
    def _market_record(item: MarketArtifact, formed_at: Any) -> dict[str, Any]:
        return {
            "id": str(item.id),
            "symbol": item.symbol,
            "timeframe": item.timeframe,
            "formed_at": formed_at,
            "known_at": item.known_at,
            "payload": item.model_dump(mode="json"),
        }

    def _upsert(self, row_type: type[Base], records: list[dict[str, Any]]) -> int:
        if not records:
            return 0
        statement = insert(row_type).values(records)
        excluded = statement.excluded
        update_columns = {key: getattr(excluded, key) for key in records[0] if key != "id"}
        statement = statement.on_conflict_do_update(index_elements=["id"], set_=update_columns)
        with Session(self._engine) as session, session.begin():
            session.execute(statement)
        return len(records)
