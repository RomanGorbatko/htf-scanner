import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import httpx
import pytest

from htf_scanner.alerts.service import AlertService, alert_dedup_key
from htf_scanner.alerts.telegram import TelegramDeliveryError, TelegramSender, escape_markdown
from htf_scanner.config import AlertsConfig, AppConfig, RetryConfig, TelegramConfig
from htf_scanner.data.binance_provider import BinanceMarketDataProvider
from htf_scanner.data.binance_rest import BinanceDataError, BinanceRestClient
from htf_scanner.domain.enums import SetupSide
from htf_scanner.domain.production import (
    AlertDeliveryStatus,
    DetectorCheckpoint,
    LiveRunStatus,
    LiveScannerRun,
    LiveSymbolRun,
    MarketInfo,
    ProductionEventType,
    ScannerEvent,
    SymbolScanStatus,
    UniverseSnapshot,
)
from htf_scanner.production.lock import ProcessLock, ScannerAlreadyRunning
from htf_scanner.production.reports import write_live_reports
from htf_scanner.production.universe import select_universe
from htf_scanner.storage.database import create_database_engine
from htf_scanner.storage.production_repository import ProductionRepository


def _event() -> ScannerEvent:
    known = datetime(2026, 1, 2, tzinfo=UTC)
    entity_id = uuid5(NAMESPACE_URL, "entity")
    return ScannerEvent(
        id=uuid5(NAMESPACE_URL, "event"),
        event_type=ProductionEventType.D1_SETUP_ACTIVE,
        entity_id=entity_id,
        symbol="TESTUSDT",
        side=SetupSide.SHORT,
        formed_at=known - timedelta(days=1),
        known_at=known,
        config_hash="a" * 64,
        payload={"context": "failed_continuation_high", "quality_score": 7.5},
    )


def test_binance_provider_normalizes_exchange_details() -> None:
    now_ms = 1_767_225_600_000

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/fapi/v1/time":
            return httpx.Response(200, json={"serverTime": now_ms})
        if request.url.path == "/fapi/v1/exchangeInfo":
            return httpx.Response(
                200,
                json={
                    "symbols": [
                        {
                            "symbol": "TESTUSDT",
                            "quoteAsset": "USDT",
                            "contractType": "PERPETUAL",
                            "status": "TRADING",
                            "onboardDate": now_ms - 400 * 86_400_000,
                        }
                    ]
                },
            )
        if request.url.path == "/fapi/v1/ticker/24hr":
            return httpx.Response(200, json=[{"symbol": "TESTUSDT", "quoteVolume": "12345.6"}])
        if request.url.path == "/fapi/v1/klines":
            open_ms = now_ms - 28_800_000
            return httpx.Response(
                200,
                json=[
                    [
                        open_ms,
                        "1",
                        "2",
                        "0.5",
                        "1.5",
                        "10",
                        open_ms + 14_400_000 - 1,
                        "15",
                        5,
                        "0",
                        "0",
                    ]
                ],
            )
        raise AssertionError(request.url)

    client = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://fapi.binance.com"
    )
    rest = BinanceRestClient(client=client)
    with BinanceMarketDataProvider(client=rest) as provider:
        markets = provider.discover_markets()
        latest = provider.fetch_latest_closed_candle("TESTUSDT", "4h")
        metadata = provider.exchange_metadata()

    assert markets[0].active
    assert markets[0].quote_volume_24h == 12345.6
    assert latest is not None and latest.symbol == "TESTUSDT"
    assert metadata.provider == "binance" and metadata.markets == 1
    client.close()


def test_binance_provider_rejects_invalid_payloads() -> None:
    responses = iter([[], {}, {}])
    rest = BinanceRestClient(
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(200, json=next(responses))
            ),
            base_url="https://fapi.binance.com",
        )
    )
    provider = BinanceMarketDataProvider(client=rest)
    with pytest.raises(BinanceDataError):
        provider.server_time()
    with pytest.raises(BinanceDataError):
        provider.discover_markets()
    with pytest.raises(ValueError, match="unsupported timeframe"):
        provider.fetch_latest_closed_candle("TESTUSDT", "1h")


def test_universe_filters_and_limits() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    markets = [
        MarketInfo(
            symbol=symbol,
            quote_asset=quote,
            contract_type="PERPETUAL",
            active=active,
            onboard_at=now - timedelta(days=days),
            quote_volume_24h=volume,
        )
        for symbol, quote, active, days, volume in (
            ("AUSDT", "USDT", True, 500, 1000),
            ("BUSDT", "USDT", True, 500, 2000),
            ("CUSDT", "USDT", False, 500, 3000),
            ("DBUSD", "BUSD", True, 500, 4000),
            ("EUSDT", "USDT", True, 10, 5000),
        )
    ]
    config = AppConfig.model_validate(
        {"universe": {"minimum_history_days": 180, "maximum_symbols": 1}}
    )
    assert [item.symbol for item in select_universe(markets, config, now)] == ["BUSDT"]


def test_process_lock_prevents_overlap_and_clears_stale(tmp_path: Path) -> None:
    path = tmp_path / "scanner.lock"
    with ProcessLock(path, timedelta(hours=1)):
        assert path.exists()
        with pytest.raises(ScannerAlreadyRunning), ProcessLock(path, timedelta(hours=1)):
            pass
    path.write_text("stale", encoding="utf-8")
    old = (datetime.now(UTC) - timedelta(days=1)).timestamp()
    os.utime(path, (old, old))
    with ProcessLock(path, timedelta(minutes=1)):
        assert path.exists()
    assert not path.exists()


def test_telegram_retries_and_escapes_markdown() -> None:
    calls = 0
    sleeps: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(500)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 42}})

    client = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://api.telegram.org"
    )
    sender = TelegramSender(
        TelegramConfig(),
        RetryConfig(attempts=2, initial_backoff_seconds=0.1),
        "token",
        "chat",
        client,
        sleeps.append,
    )
    assert sender.send(_event()) == "42"
    assert calls == 2 and sleeps == [0.1]
    assert escape_markdown("A_B.C!") == "A\\_B\\.C\\!"


def test_telegram_photo_falls_back_to_text(tmp_path: Path) -> None:
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.url.path)
        if request.url.path.endswith("sendPhoto"):
            return httpx.Response(400)
        return httpx.Response(200, json={"ok": True, "result": {}})

    chart = tmp_path / "chart.png"
    chart.write_bytes(b"png")
    sender = TelegramSender(
        TelegramConfig(),
        RetryConfig(attempts=1),
        "token",
        "chat",
        httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.telegram.org"),
        lambda _seconds: None,
    )
    assert sender.send(_event(), chart) is None
    assert methods[-1].endswith("sendMessage")


def test_telegram_raises_after_retry_exhaustion() -> None:
    sender = TelegramSender(
        TelegramConfig(),
        RetryConfig(attempts=1),
        "token",
        "chat",
        httpx.Client(
            transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
            base_url="https://api.telegram.org",
        ),
        lambda _seconds: None,
    )
    with pytest.raises(TelegramDeliveryError):
        sender.send(_event())


class _Sender:
    def __init__(self, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    def send(self, event: ScannerEvent, chart: Path | None = None) -> str:
        self.calls += 1
        if self.fail:
            raise TelegramDeliveryError("failed")
        return str(event.id)


def test_production_repository_and_alert_dedup(tmp_path: Path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'production.db'}")
    repository = ProductionRepository(engine)
    event = _event()
    repository.save_events([event])
    sender = _Sender()
    service = AlertService(repository, sender)  # type: ignore[arg-type]
    first = service.deliver(event)
    second = service.deliver(event)

    assert first.status == AlertDeliveryStatus.SENT
    assert second == first
    assert sender.calls == 1
    assert repository.event(event.id) == event
    assert repository.delivery_by_key(alert_dedup_key(event)) == first
    assert repository.delivery_backlog() == []

    failed_event = event.model_copy(
        update={
            "id": uuid5(NAMESPACE_URL, "failed-event"),
            "known_at": event.known_at + timedelta(days=1),
        }
    )
    repository.save_events([failed_event])
    failure_time = failed_event.known_at + timedelta(minutes=1)
    alert_config = AlertsConfig(
        maximum_delivery_attempts=3,
        retry_failed_after_minutes=60,
    )
    failed = AlertService(
        repository,
        _Sender(fail=True),
        alert_config,
        lambda: failure_time,
    ).deliver(failed_event)
    assert failed.status == AlertDeliveryStatus.FAILED
    assert repository.delivery_backlog() == [failed]
    assert repository.retryable_deliveries(failure_time, 3) == []
    retry_time = failure_time + timedelta(minutes=60)
    assert repository.retryable_deliveries(retry_time, 3) == [failed]
    retry_sender = _Sender()
    retried = AlertService(
        repository,
        retry_sender,
        alert_config,
        lambda: retry_time,
    ).retry_pending()
    assert retried[0].status == AlertDeliveryStatus.SENT
    assert retried[0].id == failed.id
    assert retry_sender.calls == 1

    checkpoint = DetectorCheckpoint(
        symbol="TESTUSDT",
        config_hash="a" * 64,
        scanner_version="test",
        initialized_at=event.formed_at,
        updated_at=event.known_at,
        state={"ok": True},
    )
    repository.save_checkpoint(checkpoint)
    assert repository.load_checkpoint("testusdt") == checkpoint
    assert repository.load_checkpoint("missing") is None

    run = LiveScannerRun(
        id=uuid5(NAMESPACE_URL, "run"),
        config_hash="a" * 64,
        started_at=event.formed_at,
        status=LiveRunStatus.RUNNING,
        provider="test",
    )
    symbol_run = LiveSymbolRun(
        id=uuid5(NAMESPACE_URL, "symbol-run"),
        run_id=run.id,
        symbol="TESTUSDT",
        status=SymbolScanStatus.SUCCESS,
        started_at=event.formed_at,
        completed_at=event.known_at,
    )
    market = MarketInfo(
        symbol="TESTUSDT",
        quote_asset="USDT",
        contract_type="PERPETUAL",
        active=True,
        onboard_at=event.formed_at - timedelta(days=500),
        quote_volume_24h=1000,
    )
    snapshot = UniverseSnapshot(
        id=uuid5(NAMESPACE_URL, "snapshot"),
        run_id=run.id,
        captured_at=event.known_at,
        config_hash=run.config_hash,
        markets=[market],
    )
    repository.save_run(run)
    repository.save_symbol_run(symbol_run)
    repository.save_universe(snapshot)
    paths = write_live_reports(
        tmp_path / "reports",
        run,
        [market],
        [symbol_run],
        [first, retried[0]],
        [{"symbol": "TESTUSDT", "diagnostic": "ok"}],
    )
    assert all(path.exists() for path in paths.values())
    engine.dispose()
