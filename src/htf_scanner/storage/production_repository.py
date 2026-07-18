from datetime import datetime
from uuid import UUID

from sqlalchemy import Engine, or_, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from htf_scanner.domain.production import (
    AlertDelivery,
    AlertDeliveryStatus,
    DetectorCheckpoint,
    LiveScannerRun,
    LiveSymbolRun,
    ScannerEvent,
    UniverseSnapshot,
)
from htf_scanner.storage.models import (
    AlertDeliveryRow,
    DetectorCheckpointRow,
    LiveScannerRunRow,
    LiveSymbolRunRow,
    ScannerEventRow,
    UniverseSnapshotRow,
)


class ProductionRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def load_checkpoint(self, symbol: str) -> DetectorCheckpoint | None:
        with Session(self._engine) as session:
            row = session.get(DetectorCheckpointRow, symbol.upper())
            return None if row is None else DetectorCheckpoint.model_validate(row.payload)

    def save_checkpoint(self, checkpoint: DetectorCheckpoint) -> None:
        self._upsert(
            DetectorCheckpointRow,
            {
                "symbol": checkpoint.symbol.upper(),
                "config_hash": checkpoint.config_hash,
                "updated_at": checkpoint.updated_at,
                "payload": checkpoint.model_dump(mode="json"),
            },
            ["symbol"],
        )

    def save_events(self, events: list[ScannerEvent]) -> int:
        for event in events:
            self._upsert(
                ScannerEventRow,
                {
                    "id": str(event.id),
                    "event_type": event.event_type.value,
                    "entity_id": str(event.entity_id),
                    "symbol": event.symbol,
                    "known_at": event.known_at,
                    "config_hash": event.config_hash,
                    "payload": event.model_dump(mode="json"),
                },
                ["id"],
            )
        return len(events)

    def delivery_by_key(self, dedup_key: str) -> AlertDelivery | None:
        statement = select(AlertDeliveryRow).where(AlertDeliveryRow.dedup_key == dedup_key)
        with Session(self._engine) as session:
            row = session.scalar(statement)
            return None if row is None else AlertDelivery.model_validate(row.payload)

    def retryable_deliveries(self, now: datetime, maximum_attempts: int) -> list[AlertDelivery]:
        statement = (
            select(AlertDeliveryRow)
            .where(
                AlertDeliveryRow.attempts < maximum_attempts,
                or_(
                    (
                        (AlertDeliveryRow.status == AlertDeliveryStatus.PENDING.value)
                        & (
                            AlertDeliveryRow.next_retry_at.is_(None)
                            | (AlertDeliveryRow.next_retry_at <= now)
                        )
                    ),
                    (
                        (AlertDeliveryRow.status == AlertDeliveryStatus.FAILED.value)
                        & (AlertDeliveryRow.next_retry_at <= now)
                    ),
                ),
            )
            .order_by(AlertDeliveryRow.updated_at, AlertDeliveryRow.id)
        )
        with Session(self._engine) as session:
            rows = session.scalars(statement).all()
            return [AlertDelivery.model_validate(row.payload) for row in rows]

    def delivery_backlog(self) -> list[AlertDelivery]:
        statement = (
            select(AlertDeliveryRow)
            .where(AlertDeliveryRow.status != AlertDeliveryStatus.SENT.value)
            .order_by(AlertDeliveryRow.updated_at, AlertDeliveryRow.id)
        )
        with Session(self._engine) as session:
            rows = session.scalars(statement).all()
            return [AlertDelivery.model_validate(row.payload) for row in rows]

    def save_delivery(self, delivery: AlertDelivery) -> None:
        self._upsert(
            AlertDeliveryRow,
            {
                "id": str(delivery.id),
                "dedup_key": delivery.dedup_key,
                "event_id": str(delivery.event_id),
                "status": delivery.status.value,
                "attempts": delivery.attempts,
                "next_retry_at": delivery.next_retry_at,
                "permanently_failed_at": delivery.permanently_failed_at,
                "updated_at": delivery.updated_at,
                "payload": delivery.model_dump(mode="json"),
            },
            ["dedup_key"],
        )

    def save_universe(self, snapshot: UniverseSnapshot) -> None:
        self._upsert(
            UniverseSnapshotRow,
            {
                "id": str(snapshot.id),
                "run_id": str(snapshot.run_id),
                "captured_at": snapshot.captured_at,
                "config_hash": snapshot.config_hash,
                "payload": snapshot.model_dump(mode="json"),
            },
            ["id"],
        )

    def save_run(self, run: LiveScannerRun) -> None:
        self._upsert(
            LiveScannerRunRow,
            {
                "id": str(run.id),
                "config_hash": run.config_hash,
                "started_at": run.started_at,
                "status": run.status.value,
                "payload": run.model_dump(mode="json"),
            },
            ["id"],
        )

    def save_symbol_run(self, run: LiveSymbolRun) -> None:
        self._upsert(
            LiveSymbolRunRow,
            {
                "id": str(run.id),
                "run_id": str(run.run_id),
                "symbol": run.symbol,
                "status": run.status.value,
                "payload": run.model_dump(mode="json"),
            },
            ["id"],
        )

    def event(self, event_id: UUID) -> ScannerEvent | None:
        with Session(self._engine) as session:
            row = session.get(ScannerEventRow, str(event_id))
            return None if row is None else ScannerEvent.model_validate(row.payload)

    def _upsert(
        self,
        row_type: type[object],
        record: dict[str, object],
        index_elements: list[str],
    ) -> None:
        statement = insert(row_type).values(record)
        excluded = statement.excluded
        updates = {key: getattr(excluded, key) for key in record if key not in index_elements}
        statement = statement.on_conflict_do_update(
            index_elements=index_elements,
            set_=updates,
        )
        with Session(self._engine) as session, session.begin():
            session.execute(statement)
