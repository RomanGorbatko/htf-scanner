from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter
from uuid import NAMESPACE_URL, UUID, uuid5

from htf_scanner.alerts.service import AlertService
from htf_scanner.config import AppConfig
from htf_scanner.data.cache import CandleFileCache
from htf_scanner.data.provider import MarketDataProvider
from htf_scanner.data.validation import inspect_candle_quality
from htf_scanner.detectors.d1_setup_detector import D1AnalysisResult
from htf_scanner.detectors.h4_reaction_detector import H4AnalysisResult
from htf_scanner.domain.candle import Candle
from htf_scanner.domain.production import (
    AlertDelivery,
    AlertDeliveryStatus,
    DetectorCheckpoint,
    LiveRunStatus,
    LiveScannerRun,
    LiveSymbolRun,
    MarketInfo,
    SymbolScanStatus,
    UniverseSnapshot,
)
from htf_scanner.production.incremental import CausalIncrementalBackend
from htf_scanner.production.reports import write_live_reports
from htf_scanner.production.universe import select_universe
from htf_scanner.storage.analysis_repository import AnalysisRepository
from htf_scanner.storage.production_repository import ProductionRepository
from htf_scanner.storage.repository import CandleRepository


@dataclass(frozen=True)
class LiveScanResult:
    run: LiveScannerRun
    symbols: list[LiveSymbolRun]
    universe: list[MarketInfo]
    deliveries: list[AlertDelivery]
    report_paths: dict[str, Path]


class ProductionScanner:
    def __init__(
        self,
        config: AppConfig,
        config_hash: str,
        provider: MarketDataProvider,
        candle_repository: CandleRepository,
        analysis_repository: AnalysisRepository,
        production_repository: ProductionRepository,
        file_cache: CandleFileCache,
        alert_service: AlertService | None = None,
        force_rebuild: bool = False,
    ) -> None:
        self.config = config
        self.config_hash = config_hash
        self.provider = provider
        self.candles = candle_repository
        self.analysis = analysis_repository
        self.production = production_repository
        self.file_cache = file_cache
        self.alerts = alert_service
        self.force_rebuild = force_rebuild

    def run_once(self) -> LiveScanResult:
        total_started = perf_counter()
        started_at = datetime.now(UTC)
        run_id = uuid5(
            NAMESPACE_URL,
            f"live-run:{self.config_hash}:{started_at.isoformat()}",
        )
        running = LiveScannerRun(
            id=run_id,
            config_hash=self.config_hash,
            started_at=started_at,
            status=LiveRunStatus.RUNNING,
            provider=self.config.market_data.provider,
        )
        self.production.save_run(running)
        discovery_started = perf_counter()
        try:
            server_now = self.provider.server_time()
            universe = select_universe(self.provider.discover_markets(), self.config, server_now)
        except Exception as error:
            failed_run = running.model_copy(
                update={
                    "completed_at": datetime.now(UTC),
                    "status": LiveRunStatus.FAILED,
                    "error": str(error),
                    "timings_ms": {
                        "universe_discovery": _elapsed(discovery_started),
                        "total": _elapsed(total_started),
                    },
                }
            )
            self.production.save_run(failed_run)
            paths = write_live_reports(self.config.runtime.report_dir, failed_run, [], [], [], [])
            return LiveScanResult(failed_run, [], [], [], paths)
        discovery_ms = _elapsed(discovery_started)
        snapshot = UniverseSnapshot(
            id=uuid5(NAMESPACE_URL, f"universe:{run_id}:{self.config_hash}"),
            run_id=run_id,
            captured_at=server_now,
            config_hash=self.config_hash,
            markets=universe,
        )
        self.production.save_universe(snapshot)
        symbol_runs: list[LiveSymbolRun] = []
        deliveries: list[AlertDelivery] = []
        data_quality: list[dict[str, object]] = []
        if self.alerts is not None and self.config.alerts.enabled:
            deliveries.extend(self.alerts.retry_pending())
        for market in universe:
            symbol_run, sent, quality = self._scan_symbol(run_id, market.symbol, server_now)
            symbol_runs.append(symbol_run)
            deliveries.extend(sent)
            data_quality.extend(quality)
            self.production.save_symbol_run(symbol_run)
        deliveries = _unique_deliveries(deliveries + self.production.delivery_backlog())
        failed = [item for item in symbol_runs if item.status not in _SUCCESS_STATUSES]
        status = (
            LiveRunStatus.COMPLETED
            if not failed
            else LiveRunStatus.FAILED
            if len(failed) == len(symbol_runs) and symbol_runs
            else LiveRunStatus.PARTIAL
        )
        counts = {
            "symbols_discovered": len(universe),
            "symbols_scanned": len(symbol_runs),
            "symbols_succeeded": sum(item.status in _SUCCESS_STATUSES for item in symbol_runs),
            "new_d1_setups": sum(item.new_d1_setups for item in symbol_runs),
            "new_h4_reactions": sum(item.new_h4_reactions for item in symbol_runs),
            "alerts_sent": sum(item.status == AlertDeliveryStatus.SENT for item in deliveries),
            "alerts_pending": sum(
                item.status == AlertDeliveryStatus.PENDING for item in deliveries
            ),
            "alerts_retryable_failed": sum(
                item.status == AlertDeliveryStatus.FAILED
                and item.attempts < self.config.alerts.maximum_delivery_attempts
                and item.next_retry_at is not None
                for item in deliveries
            ),
            "alerts_permanently_failed": sum(
                item.status == AlertDeliveryStatus.PERMANENTLY_FAILED for item in deliveries
            ),
            "alerts_failed": sum(
                item.status
                in {
                    AlertDeliveryStatus.FAILED,
                    AlertDeliveryStatus.PERMANENTLY_FAILED,
                }
                for item in deliveries
            ),
        }
        completed = running.model_copy(
            update={
                "completed_at": datetime.now(UTC),
                "status": status,
                "counts": counts,
                "timings_ms": {
                    "universe_discovery": discovery_ms,
                    "total": _elapsed(total_started),
                },
            }
        )
        self.production.save_run(completed)
        paths = write_live_reports(
            self.config.runtime.report_dir,
            completed,
            universe,
            symbol_runs,
            deliveries,
            data_quality,
        )
        return LiveScanResult(completed, symbol_runs, universe, deliveries, paths)

    def _scan_symbol(
        self, run_id: UUID, symbol: str, server_now: datetime
    ) -> tuple[LiveSymbolRun, list[AlertDelivery], list[dict[str, object]]]:
        started_at = datetime.now(UTC)
        started = perf_counter()
        timings: dict[str, float] = {}
        quality_rows: list[dict[str, object]] = []
        checkpoint = self.production.load_checkpoint(symbol)
        rebuilding = (
            self.force_rebuild or checkpoint is None or checkpoint.config_hash != self.config_hash
        )
        if (
            checkpoint is not None
            and rebuilding
            and not self.config.runtime.rebuild_on_config_change
        ):
            return (
                self._failure(
                    run_id,
                    symbol,
                    started_at,
                    SymbolScanStatus.DETECTOR_ERROR,
                    "configuration hash changed and rebuild is disabled",
                    timings,
                ),
                [],
                quality_rows,
            )
        fetch_started = perf_counter()
        try:
            if rebuilding:
                d1_start = _as_utc(self.config.runtime.bootstrap_start)
                h4_start = d1_start
            else:
                assert checkpoint is not None
                d1_start = _next_start(checkpoint.last_d1_close) or _as_utc(
                    self.config.runtime.bootstrap_start
                )
                h4_start = _next_start(checkpoint.last_h4_close) or _as_utc(
                    self.config.runtime.bootstrap_start
                )
            d1_new = self.provider.fetch_ohlcv(symbol, "1d", d1_start, server_now)
            h4_new = self.provider.fetch_ohlcv(symbol, "4h", h4_start, server_now)
        except Exception as error:
            timings["fetch"] = _elapsed(fetch_started)
            return (
                self._failure(
                    run_id,
                    symbol,
                    started_at,
                    SymbolScanStatus.FETCH_ERROR,
                    str(error),
                    timings,
                ),
                [],
                quality_rows,
            )
        timings["fetch"] = _elapsed(fetch_started)
        try:
            backend = (
                CausalIncrementalBackend(self.config, self.config_hash)
                if rebuilding
                else CausalIncrementalBackend.restore(
                    self.config,
                    self.config_hash,
                    checkpoint.state if checkpoint is not None else {},
                )
            )
            d1_new = self._validated_delta(symbol, "1d", backend.d1.candles, d1_new)
            h4_new = self._validated_delta(symbol, "4h", backend.h4.candles, h4_new)
        except Exception as error:
            quality_rows.append({"symbol": symbol, "status": "REJECTED", "diagnostic": str(error)})
            return (
                self._failure(
                    run_id,
                    symbol,
                    started_at,
                    SymbolScanStatus.DATA_ERROR,
                    str(error),
                    timings,
                ),
                [],
                quality_rows,
            )
        if not rebuilding and not d1_new and not h4_new:
            return (
                LiveSymbolRun(
                    id=_symbol_run_id(run_id, symbol),
                    run_id=run_id,
                    symbol=symbol,
                    status=SymbolScanStatus.NO_NEW_DATA,
                    started_at=started_at,
                    completed_at=datetime.now(UTC),
                    timings_ms={**timings, "total": _elapsed(started)},
                ),
                [],
                quality_rows,
            )
        detect_started = perf_counter()
        try:
            update = (
                backend.bootstrap(d1_new, h4_new) if rebuilding else backend.update(d1_new, h4_new)
            )
        except Exception as error:
            timings["detection"] = _elapsed(detect_started)
            return (
                self._failure(
                    run_id,
                    symbol,
                    started_at,
                    SymbolScanStatus.DETECTOR_ERROR,
                    str(error),
                    timings,
                ),
                [],
                quality_rows,
            )
        timings["detection"] = _elapsed(detect_started)
        persist_started = perf_counter()
        self._persist_candles(d1_new + h4_new)
        self._persist_analysis(update.d1, update.h4, str(run_id))
        self.production.save_events(update.events)
        enabled_events = []
        if self.alerts is not None and self.config.alerts.enabled:
            enabled = set(self.config.alerts.event_types)
            enabled_events = [event for event in update.events if event.event_type.value in enabled]
            if rebuilding and self.config.alerts.bootstrap_policy == "suppress":
                enabled_events = []
            for event in enabled_events:
                self.alerts.stage(event)
        now = datetime.now(UTC)
        self.production.save_checkpoint(
            DetectorCheckpoint(
                symbol=symbol,
                config_hash=self.config_hash,
                scanner_version=self.config.scanner.version,
                last_d1_close=backend.d1.candles[-1].close_time if backend.d1.candles else None,
                last_h4_close=backend.h4.candles[-1].close_time if backend.h4.candles else None,
                initialized_at=backend.initialized_at,
                updated_at=now,
                state=backend.export_state(),
            )
        )
        timings["persistence"] = _elapsed(persist_started)
        sent: list[AlertDelivery] = []
        if self.alerts is not None and self.config.alerts.enabled:
            chart = self._alert_chart(backend, update.d1, update.h4, symbol)
            sent = [self.alerts.deliver(event, chart) for event in enabled_events]
        failed_alerts = sum(
            item.status
            in {
                AlertDeliveryStatus.FAILED,
                AlertDeliveryStatus.PERMANENTLY_FAILED,
            }
            for item in sent
        )
        status = SymbolScanStatus.ALERT_ERROR if failed_alerts else SymbolScanStatus.SUCCESS
        new_setup_events = (
            0
            if rebuilding
            else sum(item.event_type.value == "D1_SETUP_ACTIVE" for item in update.events)
        )
        new_reaction_events = (
            0
            if rebuilding
            else sum(item.event_type.value == "H4_REACTION_CONFIRMED" for item in update.events)
        )
        return (
            LiveSymbolRun(
                id=_symbol_run_id(run_id, symbol),
                run_id=run_id,
                symbol=symbol,
                status=status,
                started_at=started_at,
                completed_at=datetime.now(UTC),
                new_d1_candles=len(d1_new),
                new_h4_candles=len(h4_new),
                new_d1_setups=new_setup_events,
                new_h4_reactions=new_reaction_events,
                alerts_sent=sum(item.status == AlertDeliveryStatus.SENT for item in sent),
                alerts_failed=failed_alerts,
                timings_ms={**timings, "total": _elapsed(started)},
            ),
            sent,
            quality_rows,
        )

    def _alert_chart(
        self,
        backend: CausalIncrementalBackend,
        d1: D1AnalysisResult,
        h4: H4AnalysisResult,
        symbol: str,
    ) -> Path | None:
        if not self.config.alerts.attach_chart or not backend.h4.candles:
            return None
        from htf_scanner.reports.charts import plot_h4_reaction_debug

        return plot_h4_reaction_debug(
            backend.h4.candles,
            d1.fvgs,
            h4.reactions,
            h4.touch_phases,
            h4.structure_breaks,
            h4.displacements,
            [],
            self.config.runtime.report_dir / "alerts" / f"{symbol}_h4.png",
        )

    @staticmethod
    def _validated_delta(
        symbol: str, timeframe: str, history: list[Candle], fetched: list[Candle]
    ) -> list[Candle]:
        expected = history[-1].open_time if history else None
        fresh = [
            item
            for item in fetched
            if item.symbol == symbol.upper() and (expected is None or item.open_time > expected)
        ]
        inspection = inspect_candle_quality(
            ([history[-1]] if history and fresh else []) + fresh,
            timeframe,
        )
        if inspection.diagnostics:
            raise ValueError("; ".join(inspection.diagnostics))
        return fresh

    def _persist_candles(self, candles: list[Candle]) -> None:
        self.candles.upsert_many(candles)
        grouped: dict[tuple[str, str], list[Candle]] = {}
        for candle in candles:
            grouped.setdefault((candle.symbol, candle.timeframe), []).append(candle)
        for (symbol, timeframe), items in grouped.items():
            self.file_cache.write(symbol, timeframe, items)

    def _persist_analysis(self, d1: D1AnalysisResult, h4: H4AnalysisResult, run_id: str) -> None:
        self.analysis.upsert_fvgs(d1.fvgs + h4.fvgs)
        self.analysis.upsert_swings(d1.swings + h4.swings)
        self.analysis.upsert_structure_breaks(d1.structure_breaks + h4.structure_breaks)
        self.analysis.upsert_structure_promotions(d1.structure_promotions)
        self.analysis.upsert_displacements(d1.displacements + h4.displacements)
        self.analysis.upsert_liquidity_interactions(d1.liquidity_interactions)
        self.analysis.upsert_liquidity_contexts(d1.liquidity_contexts)
        self.analysis.upsert_liquidity_sequences(d1.liquidity_sequences)
        self.analysis.upsert_setup_candidates(d1.setup_candidates)
        self.analysis.upsert_merged_candidates(d1.merged_candidates)
        self.analysis.upsert_setups(d1.setups)
        self.analysis.upsert_setup_transitions(d1.setup_transitions)
        self.analysis.upsert_rejected_candidates(d1.rejected_candidates)
        self.analysis.upsert_events(d1.events)
        self.analysis.upsert_h4_touch_phases(h4.touch_phases, run_id)
        self.analysis.upsert_reactions(h4.reactions, run_id)
        self.analysis.upsert_h4_candidates(h4.reaction_candidates, run_id)
        self.analysis.upsert_h4_merged_candidates(h4.merged_candidates, run_id)
        self.analysis.upsert_h4_transitions(h4.transitions, run_id)

    @staticmethod
    def _failure(
        run_id: UUID,
        symbol: str,
        started_at: datetime,
        status: SymbolScanStatus,
        error: str,
        timings: dict[str, float],
    ) -> LiveSymbolRun:
        return LiveSymbolRun(
            id=_symbol_run_id(run_id, symbol),
            run_id=run_id,
            symbol=symbol,
            status=status,
            started_at=started_at,
            completed_at=datetime.now(UTC),
            timings_ms=timings,
            error=error,
        )


_SUCCESS_STATUSES = {SymbolScanStatus.SUCCESS, SymbolScanStatus.NO_NEW_DATA}


def _elapsed(started: float) -> float:
    return (perf_counter() - started) * 1000


def _next_start(value: datetime | None) -> datetime | None:
    return value + timedelta(milliseconds=1) if value is not None else None


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _symbol_run_id(run_id: UUID, symbol: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"live-symbol:{run_id}:{symbol.upper()}")


def _unique_deliveries(items: list[AlertDelivery]) -> list[AlertDelivery]:
    return list({item.id: item for item in items}.values())
