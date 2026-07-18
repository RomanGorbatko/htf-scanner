import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest
from sqlalchemy import inspect

from htf_scanner.alerts.service import AlertService
from htf_scanner.alerts.telegram import TelegramDeliveryError
from htf_scanner.config import AlertsConfig, AppConfig, MarketDataConfig
from htf_scanner.data.binance_provider import BinanceMarketDataProvider
from htf_scanner.data.factory import ProviderConfigurationError, create_market_data_provider
from htf_scanner.domain.candle import Candle
from htf_scanner.domain.enums import SetupSide
from htf_scanner.domain.production import (
    AlertDeliveryStatus,
    ExchangeMetadata,
    MarketInfo,
    ProductionEventType,
    ScannerEvent,
)
from htf_scanner.production.doctor import DoctorError, run_doctor
from htf_scanner.storage.database import create_database_engine
from htf_scanner.storage.production_repository import ProductionRepository


def _event(name: str = "event") -> ScannerEvent:
    known_at = datetime(2026, 7, 10, tzinfo=UTC)
    return ScannerEvent(
        id=uuid5(NAMESPACE_URL, name),
        event_type=ProductionEventType.D1_SETUP_ACTIVE,
        entity_id=uuid5(NAMESPACE_URL, f"{name}:entity"),
        symbol="TESTUSDT",
        side=SetupSide.SHORT,
        formed_at=known_at - timedelta(days=1),
        known_at=known_at,
        config_hash="a" * 64,
    )


class _Sender:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    def send(self, event: ScannerEvent, chart: Path | None = None) -> str:
        self.calls += 1
        if self.fail:
            raise TelegramDeliveryError("permanent test failure")
        return str(event.id)


def test_retry_waits_then_stops_at_maximum_without_duplicate(tmp_path: Path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'retry.db'}")
    repository = ProductionRepository(engine)
    event = _event()
    repository.save_events([event])
    now = [event.known_at]
    sender = _Sender(fail=True)
    config = AlertsConfig(
        maximum_delivery_attempts=2,
        retry_failed_after_minutes=60,
    )
    service = AlertService(repository, sender, config, lambda: now[0])

    first = service.deliver(event)
    assert first.status == AlertDeliveryStatus.FAILED
    assert first.attempts == 1
    assert first.next_retry_at == now[0] + timedelta(minutes=60)
    assert service.retry_pending() == []
    assert sender.calls == 1

    now[0] += timedelta(minutes=60)
    final = service.retry_pending()[0]
    assert final.id == first.id
    assert final.status == AlertDeliveryStatus.PERMANENTLY_FAILED
    assert final.attempts == 2
    assert final.next_retry_at is None
    assert final.permanently_failed_at == now[0]
    assert final.last_error == "permanent test failure"

    now[0] += timedelta(days=1)
    assert service.retry_pending() == []
    assert sender.calls == 2
    assert repository.delivery_backlog() == [final]
    engine.dispose()


def test_pending_delivery_is_retried_in_place(tmp_path: Path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'pending.db'}")
    repository = ProductionRepository(engine)
    event = _event("pending-event")
    repository.save_events([event])
    sender = _Sender()
    service = AlertService(repository, sender, clock=lambda: event.known_at)

    pending = service.stage(event)
    sent = service.retry_pending()[0]

    assert sent.id == pending.id
    assert sent.status == AlertDeliveryStatus.SENT
    assert sent.attempts == 1
    assert sender.calls == 1
    engine.dispose()


def test_existing_alert_table_receives_additive_retry_migration(tmp_path: Path) -> None:
    database = tmp_path / "old.db"
    connection = sqlite3.connect(database)
    connection.execute(
        """
        CREATE TABLE alert_deliveries (
            id VARCHAR(36) PRIMARY KEY,
            dedup_key VARCHAR(192) NOT NULL UNIQUE,
            event_id VARCHAR(36) NOT NULL,
            status VARCHAR(16) NOT NULL,
            updated_at DATETIME NOT NULL,
            payload JSON NOT NULL
        )
        """
    )
    connection.commit()
    connection.close()

    engine = create_database_engine(f"sqlite:///{database}")
    columns = {item["name"] for item in inspect(engine).get_columns("alert_deliveries")}
    indexes = {item["name"] for item in inspect(engine).get_indexes("alert_deliveries")}

    assert {"attempts", "next_retry_at", "permanently_failed_at"} <= columns
    assert "ix_alert_delivery_status_retry" in indexes
    engine.dispose()


def test_provider_factory_honors_configuration() -> None:
    provider = create_market_data_provider(MarketDataConfig(provider="binance"))
    try:
        assert isinstance(provider, BinanceMarketDataProvider)
    finally:
        provider.close()


def test_provider_factory_rejects_unsupported_provider() -> None:
    with pytest.raises(ProviderConfigurationError, match="supported providers: binance"):
        create_market_data_provider(MarketDataConfig(provider="unsupported"))


class _DoctorProvider:
    def __init__(self, *, markets: bool = True) -> None:
        self.closed = False
        self._markets = markets
        self.now = datetime(2026, 7, 19, 12, tzinfo=UTC)

    def discover_markets(self) -> list[MarketInfo]:
        if not self._markets:
            return []
        return [
            MarketInfo(
                symbol="TESTUSDT",
                quote_asset="USDT",
                contract_type="PERPETUAL",
                active=True,
                onboard_at=self.now - timedelta(days=500),
                quote_volume_24h=1000,
            )
        ]

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        return []

    def fetch_latest_closed_candle(self, symbol: str, timeframe: str) -> Candle | None:
        return None

    def server_time(self) -> datetime:
        return self.now

    def exchange_metadata(self) -> ExchangeMetadata:
        return ExchangeMetadata(provider="fake", server_time=self.now, markets=1)

    def close(self) -> None:
        self.closed = True


def _doctor_config(tmp_path: Path) -> AppConfig:
    return AppConfig.model_validate(
        {
            "storage": {
                "database_url": f"sqlite:///{tmp_path / 'data' / 'scanner.db'}",
                "candle_cache_dir": tmp_path / "data" / "candles",
            },
            "reports": {"output_dir": tmp_path / "reports"},
            "runtime": {
                "state_dir": tmp_path / "data" / "state",
                "report_dir": tmp_path / "reports" / "live",
            },
            "scheduler": {"lock_path": tmp_path / "data" / "scanner.lock"},
            "telegram": {"enabled": True},
        }
    )


def test_doctor_validates_paths_database_provider_and_credentials(tmp_path: Path) -> None:
    config = _doctor_config(tmp_path)
    provider = _DoctorProvider()
    result = run_doctor(
        config,
        {
            config.telegram.bot_token_env: "token",
            config.telegram.chat_id_env: "chat",
        },
        provider_factory=lambda _config: provider,
    )

    assert result.provider == "binance"
    assert result.markets == 1
    assert not result.telegram_test_sent
    assert provider.closed
    assert (tmp_path / "data" / "scanner.db").exists()


def test_doctor_rejects_empty_market_discovery_and_missing_credentials(tmp_path: Path) -> None:
    config = _doctor_config(tmp_path)
    empty_provider = _DoctorProvider(markets=False)
    with pytest.raises(DoctorError, match="no markets"):
        run_doctor(
            config,
            {
                config.telegram.bot_token_env: "token",
                config.telegram.chat_id_env: "chat",
            },
            provider_factory=lambda _config: empty_provider,
        )
    assert empty_provider.closed

    provider = _DoctorProvider()
    with pytest.raises(DoctorError, match="credential environment variables"):
        run_doctor(config, {}, provider_factory=lambda _config: provider)
    assert provider.closed


def test_doctor_rejects_credential_values_without_echoing_them(tmp_path: Path) -> None:
    token = "123456:do-not-log-this-token"
    base = _doctor_config(tmp_path)
    config = base.model_copy(
        update={
            "telegram": base.telegram.model_copy(
                update={
                    "bot_token_env": token,
                    "chat_id_env": "-1001234567890",
                }
            )
        }
    )
    provider_created = False

    def provider_factory(_config: MarketDataConfig) -> _DoctorProvider:
        nonlocal provider_created
        provider_created = True
        return _DoctorProvider()

    with pytest.raises(DoctorError, match="environment variable names") as caught:
        run_doctor(config, {}, provider_factory=provider_factory)

    assert token not in str(caught.value)
    assert not provider_created
