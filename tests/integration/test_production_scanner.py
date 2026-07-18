from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import Engine

from htf_scanner.alerts.service import AlertService
from htf_scanner.config import AppConfig, configuration_hash
from htf_scanner.data.cache import CandleFileCache
from htf_scanner.domain.candle import Candle
from htf_scanner.domain.production import (
    ExchangeMetadata,
    MarketInfo,
    ScannerEvent,
    SymbolScanStatus,
)
from htf_scanner.production.scanner import ProductionScanner
from htf_scanner.storage.analysis_repository import AnalysisRepository
from htf_scanner.storage.database import create_database_engine
from htf_scanner.storage.production_repository import ProductionRepository
from htf_scanner.storage.repository import CandleRepository


class FakeProvider:
    def __init__(
        self,
        d1: list[Candle],
        h4: list[Candle],
        symbols: list[str],
        failing: set[str] | None = None,
    ) -> None:
        self.d1 = d1
        self.h4 = h4
        self.symbols = symbols
        self.failing = failing or set()
        self.now = max(d1[-1].close_time, h4[-1].close_time) + timedelta(milliseconds=1)

    def discover_markets(self) -> list[MarketInfo]:
        return [
            MarketInfo(
                symbol=symbol,
                quote_asset="USDT",
                contract_type="PERPETUAL",
                active=True,
                onboard_at=self.now - timedelta(days=1000),
                quote_volume_24h=1000,
            )
            for symbol in self.symbols
        ]

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        if symbol in self.failing:
            raise RuntimeError("exchange unavailable")
        source = self.d1 if timeframe == "1d" else self.h4
        return [item for item in source if start <= item.open_time < end]

    def fetch_latest_closed_candle(self, symbol: str, timeframe: str) -> Candle | None:
        items = self.d1 if timeframe == "1d" else self.h4
        return items[-1] if items else None

    def server_time(self) -> datetime:
        return self.now

    def exchange_metadata(self) -> ExchangeMetadata:
        return ExchangeMetadata(provider="fake", server_time=self.now, markets=len(self.symbols))

    def close(self) -> None:
        pass


class DiscoveryFailureProvider(FakeProvider):
    def server_time(self) -> datetime:
        raise RuntimeError("server time unavailable")


def _scanner(
    tmp_path: Path,
    config: AppConfig,
    provider: FakeProvider,
    alert_service: AlertService | None = None,
    *,
    force_rebuild: bool = False,
) -> tuple[ProductionScanner, ProductionRepository, Engine]:
    engine = create_database_engine(config.storage.database_url)
    production = ProductionRepository(engine)
    scanner = ProductionScanner(
        config,
        configuration_hash(config),
        provider,
        CandleRepository(engine),
        AnalysisRepository(engine),
        production,
        CandleFileCache(config.storage.candle_cache_dir),
        alert_service,
        force_rebuild=force_rebuild,
    )
    return scanner, production, engine


class RecordingSender:
    def __init__(self) -> None:
        self.events: list[ScannerEvent] = []

    def send(self, event: ScannerEvent, chart: Path | None = None) -> str:
        self.events.append(event)
        return str(event.id)


def test_live_scanner_isolates_fetch_failure_and_resumes_checkpoint(tmp_path: Path) -> None:
    fixture = CandleFileCache(Path("tests/fixtures"))
    d1 = fixture.read("JTOUSDT", "1d")
    h4 = fixture.read("JTOUSDT", "4h")
    config = AppConfig.model_validate(
        {
            "storage": {
                "database_url": f"sqlite:///{tmp_path / 'live.db'}",
                "candle_cache_dir": str(tmp_path / "candles"),
            },
            "universe": {
                "minimum_history_days": 0,
                "include": ["JTOUSDT", "BADUSDT"],
            },
            "runtime": {
                "bootstrap_start": d1[0].open_time,
                "report_dir": str(tmp_path / "reports"),
            },
        }
    )
    provider = FakeProvider(d1, h4, ["JTOUSDT", "BADUSDT"], {"BADUSDT"})
    scanner, repository, engine = _scanner(tmp_path, config, provider)

    first = scanner.run_once()
    statuses = {item.symbol: item.status for item in first.symbols}
    assert statuses == {
        "BADUSDT": SymbolScanStatus.FETCH_ERROR,
        "JTOUSDT": SymbolScanStatus.SUCCESS,
    }
    assert first.run.status.value == "PARTIAL"
    checkpoint = repository.load_checkpoint("JTOUSDT")
    assert checkpoint is not None
    assert checkpoint.last_d1_close == d1[-1].close_time
    assert set(path.name for path in first.report_paths.values()) == {
        "run_manifest.json",
        "universe_snapshot.csv",
        "run_summary.csv",
        "symbol_summary.csv",
        "alerts_sent.csv",
        "alerts_pending.csv",
        "data_quality.csv",
        "runtime_metrics.csv",
    }

    second = scanner.run_once()
    statuses = {item.symbol: item.status for item in second.symbols}
    assert statuses["JTOUSDT"] == SymbolScanStatus.NO_NEW_DATA
    assert statuses["BADUSDT"] == SymbolScanStatus.FETCH_ERROR
    provider.symbols = []
    third = scanner.run_once()
    assert third.universe == []
    assert third.run.counts["symbols_scanned"] == 0
    assert third.run.status.value == "COMPLETED"
    engine.dispose()


def test_live_scanner_rejects_gapped_candles(tmp_path: Path) -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)

    def candle(offset: timedelta, timeframe: str, interval: timedelta) -> Candle:
        opened = start + offset
        return Candle(
            symbol="GAPUSDT",
            timeframe=timeframe,
            open_time=opened,
            close_time=opened + interval - timedelta(milliseconds=1),
            open=Decimal("1"),
            high=Decimal("2"),
            low=Decimal("0.5"),
            close=Decimal("1.5"),
            volume=Decimal("10"),
        )

    d1 = [
        candle(timedelta(0), "1d", timedelta(days=1)),
        candle(timedelta(days=2), "1d", timedelta(days=1)),
    ]
    h4 = [candle(timedelta(0), "4h", timedelta(hours=4))]
    config = AppConfig.model_validate(
        {
            "storage": {
                "database_url": f"sqlite:///{tmp_path / 'gap.db'}",
                "candle_cache_dir": str(tmp_path / "candles"),
            },
            "universe": {"minimum_history_days": 0, "include": ["GAPUSDT"]},
            "runtime": {
                "bootstrap_start": start,
                "report_dir": str(tmp_path / "reports"),
            },
        }
    )
    scanner, _repository, engine = _scanner(tmp_path, config, FakeProvider(d1, h4, ["GAPUSDT"]))
    result = scanner.run_once()

    assert result.symbols[0].status == SymbolScanStatus.DATA_ERROR
    assert result.run.status.value == "FAILED"
    engine.dispose()


def test_live_scanner_persists_global_discovery_failure(tmp_path: Path) -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candle = Candle(
        symbol="TESTUSDT",
        timeframe="1d",
        open_time=start,
        close_time=start + timedelta(days=1) - timedelta(milliseconds=1),
        open=Decimal("1"),
        high=Decimal("2"),
        low=Decimal("0.5"),
        close=Decimal("1.5"),
        volume=Decimal("10"),
    )
    h4 = candle.model_copy(
        update={
            "timeframe": "4h",
            "close_time": start + timedelta(hours=4) - timedelta(milliseconds=1),
        }
    )
    config = AppConfig.model_validate(
        {
            "storage": {
                "database_url": f"sqlite:///{tmp_path / 'failure.db'}",
                "candle_cache_dir": str(tmp_path / "candles"),
            },
            "runtime": {"report_dir": str(tmp_path / "reports")},
        }
    )
    scanner, _repository, engine = _scanner(
        tmp_path,
        config,
        DiscoveryFailureProvider([candle], [h4], ["TESTUSDT"]),
    )
    result = scanner.run_once()

    assert result.run.status.value == "FAILED"
    assert result.run.error == "server time unavailable"
    assert result.symbols == []
    assert result.report_paths["manifest"].exists()
    engine.dispose()


def test_bootstrap_and_rebuild_suppress_history_but_new_event_is_sent_once(
    tmp_path: Path,
) -> None:
    fixture = CandleFileCache(Path("tests/fixtures"))
    all_d1 = fixture.read("JTOUSDT", "1d")
    all_h4 = fixture.read("JTOUSDT", "4h")
    cutoff = datetime(2026, 7, 9, tzinfo=UTC)
    initial_d1 = [item for item in all_d1 if item.open_time < cutoff]
    initial_h4 = [item for item in all_h4 if item.open_time < cutoff]
    config = AppConfig.model_validate(
        {
            "storage": {
                "database_url": f"sqlite:///{tmp_path / 'bootstrap.db'}",
                "candle_cache_dir": str(tmp_path / "candles"),
            },
            "universe": {
                "minimum_history_days": 0,
                "include": ["JTOUSDT"],
            },
            "alerts": {
                "bootstrap_policy": "suppress",
                "event_types": ["D1_SETUP_ACTIVE"],
            },
            "runtime": {
                "bootstrap_start": all_d1[0].open_time,
                "report_dir": str(tmp_path / "reports"),
            },
        }
    )
    provider = FakeProvider(initial_d1, initial_h4, ["JTOUSDT"])
    engine = create_database_engine(config.storage.database_url)
    repository = ProductionRepository(engine)
    sender = RecordingSender()

    def build(current: AppConfig, *, rebuild: bool = False) -> ProductionScanner:
        return ProductionScanner(
            current,
            configuration_hash(current),
            provider,
            CandleRepository(engine),
            AnalysisRepository(engine),
            repository,
            CandleFileCache(current.storage.candle_cache_dir),
            AlertService(repository, sender, current.alerts),
            force_rebuild=rebuild,
        )

    first = build(config).run_once()
    checkpoint = repository.load_checkpoint("JTOUSDT")
    with engine.connect() as connection:
        historical_event_count = connection.exec_driver_sql(
            "SELECT COUNT(*) FROM scanner_events"
        ).scalar_one()

    assert first.symbols[0].status == SymbolScanStatus.SUCCESS
    assert checkpoint is not None
    assert historical_event_count > 0
    assert sender.events == []
    assert repository.delivery_backlog() == []

    provider.d1 = all_d1
    provider.h4 = all_h4
    provider.now = max(all_d1[-1].close_time, all_h4[-1].close_time) + timedelta(milliseconds=1)
    second = build(config).run_once()
    assert second.symbols[0].new_d1_setups == 1
    assert len(sender.events) == 1
    sent_event_id = sender.events[0].id

    third = build(config).run_once()
    assert third.symbols[0].status == SymbolScanStatus.NO_NEW_DATA
    assert [item.id for item in sender.events] == [sent_event_id]

    build(config, rebuild=True).run_once()
    assert [item.id for item in sender.events] == [sent_event_id]

    changed = config.model_copy(
        update={"alerts": config.alerts.model_copy(update={"retry_failed_after_minutes": 61})}
    )
    changed_result = build(changed).run_once()
    assert changed_result.symbols[0].status == SymbolScanStatus.SUCCESS
    assert [item.id for item in sender.events] == [sent_event_id]
    assert repository.load_checkpoint("JTOUSDT").config_hash == configuration_hash(changed)  # type: ignore[union-attr]
    engine.dispose()
