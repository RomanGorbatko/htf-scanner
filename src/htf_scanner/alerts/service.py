from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from htf_scanner.alerts.telegram import TelegramDeliveryError
from htf_scanner.config import AlertsConfig
from htf_scanner.domain.production import (
    AlertDelivery,
    AlertDeliveryStatus,
    ScannerEvent,
)
from htf_scanner.storage.production_repository import ProductionRepository


def alert_dedup_key(event: ScannerEvent) -> str:
    transition = str(event.transition_id) if event.transition_id else event.known_at.isoformat()
    return ":".join([event.event_type.value, str(event.entity_id), transition, event.config_hash])


class AlertService:
    def __init__(
        self,
        repository: ProductionRepository,
        sender: "AlertSender",
        config: AlertsConfig | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._sender = sender
        self._config = config or AlertsConfig()
        self._clock = clock or (lambda: datetime.now(UTC))

    def stage(self, event: ScannerEvent) -> AlertDelivery:
        key = alert_dedup_key(event)
        existing = self._repository.delivery_by_key(key)
        if existing is not None:
            return existing
        now = self._clock()
        delivery = AlertDelivery(
            id=uuid5(NAMESPACE_URL, f"alert:{key}"),
            dedup_key=key,
            event_id=event.id,
            status=AlertDeliveryStatus.PENDING,
            created_at=now,
            updated_at=now,
            next_retry_at=now,
        )
        self._repository.save_delivery(delivery)
        return delivery

    def deliver(self, event: ScannerEvent, chart: Path | None = None) -> AlertDelivery:
        delivery = self.stage(event)
        now = self._clock()
        if delivery.status in {
            AlertDeliveryStatus.SENT,
            AlertDeliveryStatus.PERMANENTLY_FAILED,
        }:
            return delivery
        if delivery.status in {
            AlertDeliveryStatus.PENDING,
            AlertDeliveryStatus.FAILED,
        } and (delivery.next_retry_at is not None and delivery.next_retry_at > now):
            return delivery
        if delivery.attempts >= self._config.maximum_delivery_attempts:
            permanent = delivery.model_copy(
                update={
                    "status": AlertDeliveryStatus.PERMANENTLY_FAILED,
                    "updated_at": now,
                    "next_retry_at": None,
                    "permanently_failed_at": now,
                }
            )
            self._repository.save_delivery(permanent)
            return permanent
        try:
            message_id = self._sender.send(event, chart)
        except TelegramDeliveryError as error:
            attempts = delivery.attempts + 1
            is_permanent = attempts >= self._config.maximum_delivery_attempts
            failed = delivery.model_copy(
                update={
                    "status": (
                        AlertDeliveryStatus.PERMANENTLY_FAILED
                        if is_permanent
                        else AlertDeliveryStatus.FAILED
                    ),
                    "attempts": attempts,
                    "updated_at": now,
                    "next_retry_at": (
                        None
                        if is_permanent
                        else now + timedelta(minutes=self._config.retry_failed_after_minutes)
                    ),
                    "permanently_failed_at": now if is_permanent else None,
                    "last_error": str(error),
                }
            )
            self._repository.save_delivery(failed)
            return failed
        sent = delivery.model_copy(
            update={
                "status": AlertDeliveryStatus.SENT,
                "attempts": delivery.attempts + 1,
                "updated_at": now,
                "next_retry_at": None,
                "sent_at": now,
                "permanently_failed_at": None,
                "last_error": None,
                "provider_message_id": message_id,
            }
        )
        self._repository.save_delivery(sent)
        return sent

    def retry_pending(self) -> list[AlertDelivery]:
        retried: list[AlertDelivery] = []
        now = self._clock()
        for delivery in self._repository.retryable_deliveries(
            now, self._config.maximum_delivery_attempts
        ):
            event = self._repository.event(delivery.event_id)
            if event is not None:
                retried.append(self.deliver(event))
        return retried


class AlertSender(Protocol):
    def send(self, event: ScannerEvent, chart: Path | None = None) -> str | None: ...
