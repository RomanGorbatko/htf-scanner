from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated
from uuid import NAMESPACE_URL, uuid5

import typer

from htf_scanner.batch import BatchUniverseResult
from htf_scanner.config import AppConfig, configuration_hash, load_config
from htf_scanner.data.binance_rest import BinanceRestClient, validate_candles
from htf_scanner.data.cache import CandleFileCache
from htf_scanner.data.downloader import CandleDownloader
from htf_scanner.detectors.fvg_detector import detect_fvgs
from htf_scanner.domain.candle import Candle
from htf_scanner.domain.enums import ScannerRunStatus
from htf_scanner.domain.run import ScannerRun
from htf_scanner.pipeline import SymbolAnalysisResult
from htf_scanner.storage.analysis_repository import AnalysisRepository
from htf_scanner.storage.database import create_database_engine
from htf_scanner.storage.repository import CandleRepository

app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)


@app.callback()
def main() -> None:
    """Causal higher-timeframe market scanner."""


@app.command("inspect-fvg")
def inspect_fvg(
    symbol: Annotated[str, typer.Option(help="Binance perpetual symbol, for example JTOUSDT")],
    start: Annotated[datetime, typer.Option(help="Inclusive UTC start date")],
    end: Annotated[datetime, typer.Option(help="Exclusive UTC end date")],
    config_path: Annotated[Path | None, typer.Option("--config", help="YAML config path")] = None,
    offline: Annotated[bool, typer.Option(help="Use cached SQLite candles only")] = False,
) -> None:
    """Download, detect, and chart raw D1 fair value gaps."""
    config = load_config(config_path)
    start_at = _as_utc(start)
    requested_end = _as_utc(end)
    if requested_end <= start_at:
        raise typer.BadParameter("--end must be after --start")
    analysis_end = min(requested_end, datetime.now(UTC))
    if analysis_end < requested_end:
        typer.echo(
            f"End date is in the future; using closed candles before {analysis_end.isoformat()}."
        )

    engine = create_database_engine(config.storage.database_url)
    repository = CandleRepository(engine)
    file_cache = CandleFileCache(config.storage.candle_cache_dir)
    if not offline:
        with BinanceRestClient() as client:
            downloader = CandleDownloader(client, repository, file_cache)
            for timeframe in ("1d", "4h"):
                downloaded = downloader.download(symbol, timeframe, start_at, analysis_end)
                typer.echo(f"Downloaded {len(downloaded)} closed {timeframe} candles.")
    else:
        for timeframe in ("1d", "4h"):
            cached = [
                candle
                for candle in file_cache.read(symbol, timeframe)
                if start_at <= candle.open_time < analysis_end and candle.is_closed
            ]
            repository.upsert_many(cached)
            typer.echo(f"Loaded {len(cached)} cached {timeframe} candles.")

    d1_candles = repository.list_range(symbol, "1d", start_at, analysis_end)
    h4_candles = repository.list_range(symbol, "4h", start_at, analysis_end)
    if not d1_candles:
        raise typer.BadParameter("no cached D1 candles found for the requested range")
    validate_candles(d1_candles, "1d")
    validate_candles(h4_candles, "4h")

    fvgs = detect_fvgs(d1_candles, config.atr.period, config.fvg)
    from htf_scanner.reports.charts import plot_d1_fvgs
    from htf_scanner.reports.exports import export_fvgs_csv

    report_dir = config.reports.output_dir / symbol.upper()
    csv_path = export_fvgs_csv(fvgs, report_dir / "d1_fvgs.csv")
    chart_path = plot_d1_fvgs(d1_candles, fvgs, report_dir / "d1_fvgs.png")
    typer.echo(
        f"Detected {len(fvgs)} qualified raw D1 FVGs "
        f"({sum(fvg.side.value == 'bearish' for fvg in fvgs)} bearish, "
        f"{sum(fvg.side.value == 'bullish' for fvg in fvgs)} bullish)."
    )
    typer.echo(f"CSV: {csv_path}")
    typer.echo(f"Chart: {chart_path}")
    engine.dispose()


@app.command("detect-d1-setups")
def detect_d1_setup_command(
    symbol: Annotated[str, typer.Option(help="Binance perpetual symbol, for example JTOUSDT")],
    start: Annotated[datetime, typer.Option(help="Inclusive UTC start date")] = datetime(
        2025, 1, 1
    ),
    end: Annotated[datetime | None, typer.Option(help="Exclusive UTC end date")] = None,
    config_path: Annotated[Path | None, typer.Option("--config", help="YAML config path")] = None,
    offline: Annotated[bool, typer.Option(help="Use cached candles only")] = False,
) -> None:
    """Detect causal D1 structure and classified HTF setup candidates."""
    from htf_scanner.detectors.d1_setup_detector import detect_d1_setups
    from htf_scanner.reports.charts import plot_d1_setup_debug
    from htf_scanner.reports.exports import export_domain_csv

    config = load_config(config_path)
    config_hash = configuration_hash(config)
    start_at = _as_utc(start)
    now = datetime.now(UTC)
    end_at = min(_as_utc(end), now) if end is not None else now
    if end_at <= start_at:
        raise typer.BadParameter("--end must be after --start")
    engine = create_database_engine(config.storage.database_url)
    candle_repository = CandleRepository(engine)
    analysis_repository = AnalysisRepository(engine)
    file_cache = CandleFileCache(config.storage.candle_cache_dir)
    if offline:
        all_cached = file_cache.read(symbol, "1d")
        if end is None and all_cached:
            end_at = max(candle.close_time for candle in all_cached) + timedelta(milliseconds=1)
        cached = [
            candle
            for candle in all_cached
            if start_at <= candle.open_time < end_at and candle.is_closed
        ]
        candle_repository.upsert_many(cached)
        typer.echo(f"Loaded {len(cached)} cached 1d candles.")
    else:
        with BinanceRestClient() as client:
            downloader = CandleDownloader(client, candle_repository, file_cache)
            downloaded = downloader.download(symbol, "1d", start_at, end_at)
            typer.echo(f"Downloaded {len(downloaded)} closed 1d candles.")
    if end_at <= start_at:
        raise typer.BadParameter("--end must be after --start")
    candles = candle_repository.list_range(symbol, "1d", start_at, end_at)
    if not candles:
        raise typer.BadParameter("no cached D1 candles found for the requested range")
    validate_candles(candles, "1d")
    started_at = datetime.now(UTC)
    run_id = uuid5(
        NAMESPACE_URL,
        f"d1-setups:{symbol.upper()}:{start_at.isoformat()}:{end_at.isoformat()}:{config_hash}",
    )
    result = detect_d1_setups(candles, config, config_hash)
    counts = {
        "candles": len(candles),
        "fvgs": len(result.fvgs),
        "swings": len(result.swings),
        "structure_breaks": len(result.structure_breaks),
        "structure_promotions": len(result.structure_promotions),
        "displacements": len(result.displacements),
        "liquidity_interactions": len(result.liquidity_interactions),
        "liquidity_contexts": len(result.liquidity_contexts),
        "liquidity_sequences": len(result.liquidity_sequences),
        "setup_candidates": len(result.setup_candidates),
        "merged_candidates": len(result.merged_candidates),
        "setups": len(result.setups),
        "setup_transitions": len(result.setup_transitions),
        "rejected_candidates": len(result.rejected_candidates),
    }
    scanner_run = ScannerRun(
        id=run_id,
        scanner_version=config.scanner.version,
        config_hash=config_hash,
        symbol=symbol.upper(),
        timeframe="1d",
        start_at=start_at,
        end_at=end_at,
        started_at=started_at,
        completed_at=datetime.now(UTC),
        status=ScannerRunStatus.COMPLETED,
        counts=counts,
    )
    analysis_repository.upsert_fvgs(result.fvgs)
    analysis_repository.upsert_swings(result.swings)
    analysis_repository.upsert_structure_breaks(result.structure_breaks)
    analysis_repository.upsert_structure_promotions(result.structure_promotions)
    analysis_repository.upsert_displacements(result.displacements)
    analysis_repository.upsert_liquidity_interactions(result.liquidity_interactions)
    analysis_repository.upsert_liquidity_contexts(result.liquidity_contexts)
    analysis_repository.upsert_liquidity_sequences(result.liquidity_sequences)
    analysis_repository.upsert_setup_candidates(result.setup_candidates)
    analysis_repository.upsert_merged_candidates(result.merged_candidates)
    analysis_repository.upsert_setups(result.setups)
    analysis_repository.upsert_setup_transitions(result.setup_transitions)
    analysis_repository.upsert_rejected_candidates(result.rejected_candidates)
    analysis_repository.upsert_events(result.events)
    analysis_repository.upsert_runs([scanner_run])

    report_dir = config.reports.output_dir / symbol.upper()
    export_domain_csv(result.swings, report_dir / "d1_swings.csv", ["id"])
    export_domain_csv(result.structure_breaks, report_dir / "d1_structure_breaks.csv", ["id"])
    export_domain_csv(
        result.structure_promotions, report_dir / "d1_structure_promotions.csv", ["id"]
    )
    export_domain_csv(result.displacements, report_dir / "d1_displacements.csv", ["id"])
    export_domain_csv(
        result.liquidity_interactions,
        report_dir / "d1_liquidity_interactions.csv",
        ["id"],
    )
    export_domain_csv(result.liquidity_contexts, report_dir / "d1_liquidity_contexts.csv", ["id"])
    export_domain_csv(result.liquidity_sequences, report_dir / "d1_liquidity_sequences.csv", ["id"])
    export_domain_csv(result.setup_candidates, report_dir / "d1_setup_candidates.csv", ["id"])
    setup_path = export_domain_csv(result.setups, report_dir / "d1_setups.csv", ["id"])
    export_domain_csv(result.setup_transitions, report_dir / "d1_setup_transitions.csv", ["id"])
    rejected_path = export_domain_csv(
        result.rejected_candidates, report_dir / "d1_rejected_candidates.csv", ["id"]
    )
    export_domain_csv(result.merged_candidates, report_dir / "d1_merged_candidates.csv", ["id"])
    chart_path = plot_d1_setup_debug(
        candles,
        result.fvgs,
        result.swings,
        result.structure_breaks,
        result.structure_promotions,
        result.structure_snapshots,
        result.liquidity_interactions,
        result.liquidity_sequences,
        result.displacements,
        result.liquidity_contexts,
        result.setups,
        report_dir / "d1_setups.png",
    )
    typer.echo("D1 analysis: " + ", ".join(f"{key}={value}" for key, value in counts.items()))
    typer.echo(f"Setups CSV: {setup_path}")
    typer.echo(f"Rejected candidates CSV: {rejected_path}")
    typer.echo(f"Debug chart: {chart_path}")
    typer.echo(f"Run ID: {scanner_run.id}; config hash: {config_hash}")
    engine.dispose()


@app.command("detect-h4-reactions")
def detect_h4_reactions_command(
    symbol: Annotated[str, typer.Option(help="Binance perpetual symbol")],
    start: Annotated[datetime, typer.Option(help="Inclusive UTC start date")] = datetime(
        2025, 1, 1
    ),
    end: Annotated[datetime | None, typer.Option(help="Exclusive UTC end date")] = None,
    config_path: Annotated[Path | None, typer.Option("--config", help="YAML config path")] = None,
    offline: Annotated[bool, typer.Option(help="Use cached candles only")] = False,
    d1_candles_path: Annotated[
        Path | None, typer.Option("--d1-candles", help="D1 CSV or JSONL path")
    ] = None,
    h4_candles_path: Annotated[
        Path | None, typer.Option("--h4-candles", help="H4 CSV or JSONL path")
    ] = None,
    output: Annotated[Path | None, typer.Option(help="Report output directory")] = None,
) -> None:
    """Detect causal H4 zone interactions, reactions, and outcome snapshots."""
    config = load_config(config_path)
    config_hash = configuration_hash(config)
    d1_candles, h4_candles = _load_h4_inputs(
        symbol,
        start,
        end,
        offline,
        d1_candles_path,
        h4_candles_path,
        config,
    )
    from htf_scanner.pipeline import analyze_symbol

    result = analyze_symbol(d1_candles, h4_candles, config, config_hash)
    engine = create_database_engine(config.storage.database_url)
    run_id = uuid5(
        NAMESPACE_URL,
        f"h4-reactions:{symbol.upper()}:{d1_candles[0].open_time.isoformat()}:"
        f"{h4_candles[-1].close_time.isoformat()}:{config_hash}",
    )
    repository = AnalysisRepository(engine)
    _persist_h4_result(repository, result, str(run_id))
    repository.upsert_runs(
        [
            ScannerRun(
                id=run_id,
                scanner_version=config.scanner.version,
                config_hash=config_hash,
                symbol=symbol.upper(),
                timeframe="1d+4h",
                start_at=min(d1_candles[0].open_time, h4_candles[0].open_time),
                end_at=max(d1_candles[-1].close_time, h4_candles[-1].close_time),
                started_at=min(d1_candles[0].open_time, h4_candles[0].open_time),
                completed_at=max(d1_candles[-1].close_time, h4_candles[-1].close_time),
                status=ScannerRunStatus.COMPLETED,
                counts={
                    "d1_setups": len(result.d1.setups),
                    "h4_reactions": len(result.h4.reactions),
                    "outcomes": len(result.outcomes.outcomes),
                },
            )
        ]
    )
    report_dir = output or config.reports.output_dir / symbol.upper()
    paths = _write_h4_reports(h4_candles, result, report_dir)
    typer.echo(
        "H4 analysis: "
        f"setups={len(result.d1.setups)}, touch_phases={len(result.h4.touch_phases)}, "
        f"reactions={len(result.h4.reactions)}, "
        f"confirmed={sum(item.confirmed_at is not None for item in result.h4.reactions)}, "
        f"outcomes={len(result.outcomes.outcomes)}"
    )
    typer.echo(f"Reactions CSV: {paths['reactions']}")
    typer.echo(f"Diagnostics: {paths['diagnostics']}")
    typer.echo(f"Debug chart: {paths['chart']}")
    engine.dispose()


@app.command("evaluate-reaction-outcomes")
def evaluate_reaction_outcomes_command(
    symbol: Annotated[str, typer.Option(help="Binance perpetual symbol")],
    start: Annotated[datetime, typer.Option(help="Inclusive UTC start date")] = datetime(
        2025, 1, 1
    ),
    end: Annotated[datetime | None, typer.Option(help="Exclusive UTC end date")] = None,
    config_path: Annotated[Path | None, typer.Option("--config", help="YAML config path")] = None,
    offline: Annotated[bool, typer.Option(help="Use cached candles only")] = True,
    d1_candles_path: Annotated[
        Path | None, typer.Option("--d1-candles", help="D1 CSV or JSONL path")
    ] = None,
    h4_candles_path: Annotated[
        Path | None, typer.Option("--h4-candles", help="H4 CSV or JSONL path")
    ] = None,
    output: Annotated[Path | None, typer.Option(help="Report output directory")] = None,
) -> None:
    """Replay confirmed reactions and write immutable outcome horizons."""
    config = load_config(config_path)
    config_hash = configuration_hash(config)
    d1_candles, h4_candles = _load_h4_inputs(
        symbol,
        start,
        end,
        offline,
        d1_candles_path,
        h4_candles_path,
        config,
    )
    from htf_scanner.pipeline import analyze_symbol
    from htf_scanner.reports.exports import export_domain_csv

    result = analyze_symbol(d1_candles, h4_candles, config, config_hash)
    run_id = uuid5(
        NAMESPACE_URL,
        f"reaction-outcomes:{symbol.upper()}:{h4_candles[-1].close_time.isoformat()}:{config_hash}",
    )
    engine = create_database_engine(config.storage.database_url)
    _persist_h4_result(AnalysisRepository(engine), result, str(run_id))
    engine.dispose()
    report_dir = output or config.reports.output_dir / symbol.upper()
    outcomes_path = export_domain_csv(
        result.outcomes.outcomes, report_dir / "reaction_outcomes.csv", ["id"]
    )
    targets_path = export_domain_csv(
        result.outcomes.target_outcomes,
        report_dir / "reaction_target_outcomes.csv",
        ["id"],
    )
    typer.echo(f"Outcome snapshots: {len(result.outcomes.outcomes)}; CSV: {outcomes_path}")
    typer.echo(f"Target snapshots: {len(result.outcomes.target_outcomes)}; CSV: {targets_path}")


@app.command("scan-universe")
def scan_universe_command(
    symbols: Annotated[str | None, typer.Option(help="Comma-separated perpetual symbols")] = None,
    symbols_file: Annotated[
        Path | None, typer.Option("--symbols-file", help="One symbol per line")
    ] = None,
    data_dir: Annotated[Path | None, typer.Option(help="Offline candle cache root")] = None,
    config_path: Annotated[Path | None, typer.Option("--config", help="YAML config path")] = None,
    output: Annotated[Path | None, typer.Option(help="Batch report directory")] = None,
) -> None:
    """Run an isolated deterministic offline scan for a controlled symbol list."""
    from htf_scanner.batch import scan_offline_universe

    config = load_config(config_path)
    config_hash = configuration_hash(config)
    requested = [item for item in (symbols or "").split(",") if item.strip()]
    if symbols_file is not None:
        requested.extend(
            line.strip()
            for line in symbols_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
    cache = CandleFileCache(data_dir or config.storage.candle_cache_dir)
    result = scan_offline_universe(requested, cache, config, config_hash)
    engine = create_database_engine(config.storage.database_url)
    repository = AnalysisRepository(engine)
    repository.upsert_batch_runs([result.run])
    repository.upsert_batch_symbol_runs(result.symbol_runs)
    for symbol in sorted(result.analyses):
        _persist_h4_result(repository, result.analyses[symbol], str(result.run.id))
    report_dir = output or config.reports.output_dir / "universe"
    _write_batch_reports(result, report_dir)
    typer.echo(
        "Universe scan: " + ", ".join(f"{key}={value}" for key, value in result.run.counts.items())
    )
    typer.echo(
        "Runtime ms (volatile): "
        + ", ".join(
            f"{symbol}={runtime:.2f}"
            for symbol, runtime in sorted(result.runtime_measurements_ms.items())
        )
    )
    typer.echo(f"Manifest hash: {result.run.manifest_hash}")
    engine.dispose()
    if result.run.status.value == "failed":
        raise typer.Exit(code=1)


@app.command("scan-live-once")
def scan_live_once_command(
    config_path: Annotated[Path | None, typer.Option("--config", help="YAML config path")] = None,
    rebuild: Annotated[
        bool, typer.Option("--rebuild", help="Discard checkpoints and bootstrap all symbols")
    ] = False,
    no_alerts: Annotated[
        bool, typer.Option("--no-alerts", help="Run detection without Telegram delivery")
    ] = False,
) -> None:
    """Run one lock-protected production scan for all configured markets."""
    import os

    from htf_scanner.alerts.service import AlertService
    from htf_scanner.alerts.telegram import TelegramSender
    from htf_scanner.data.factory import (
        ProviderConfigurationError,
        create_market_data_provider,
    )
    from htf_scanner.production.lock import ProcessLock, ScannerAlreadyRunning
    from htf_scanner.production.scanner import ProductionScanner
    from htf_scanner.storage.production_repository import ProductionRepository

    try:
        config = load_config(config_path)
    except Exception as error:
        typer.echo(f"Configuration failed: {error}", err=True)
        raise typer.Exit(code=2) from error
    config_hash = configuration_hash(config)
    stale_after = timedelta(minutes=config.scheduler.stale_after_minutes)
    try:
        with ProcessLock(config.scheduler.lock_path, stale_after):
            engine = create_database_engine(config.storage.database_url)
            try:
                try:
                    provider = create_market_data_provider(config.market_data)
                except ProviderConfigurationError as error:
                    typer.echo(str(error), err=True)
                    raise typer.Exit(code=2) from error
                sender: TelegramSender | None = None
                try:
                    production_repository = ProductionRepository(engine)
                    alert_service: AlertService | None = None
                    if config.telegram.enabled and not no_alerts:
                        sender = TelegramSender(
                            config.telegram,
                            config.retry,
                            os.environ.get(config.telegram.bot_token_env, ""),
                            os.environ.get(config.telegram.chat_id_env, ""),
                        )
                        alert_service = AlertService(
                            production_repository,
                            sender,
                            config.alerts,
                        )
                    scanner = ProductionScanner(
                        config,
                        config_hash,
                        provider,
                        CandleRepository(engine),
                        AnalysisRepository(engine),
                        production_repository,
                        CandleFileCache(config.storage.candle_cache_dir),
                        alert_service,
                        force_rebuild=rebuild,
                    )
                    result = scanner.run_once()
                finally:
                    if sender is not None:
                        sender.close()
                    provider.close()
            finally:
                engine.dispose()
    except ScannerAlreadyRunning as error:
        typer.echo(str(error))
        raise typer.Exit(code=75) from error
    except typer.Exit:
        raise
    except Exception as error:
        message = str(error) if str(error) else error.__class__.__name__
        typer.echo(f"Live scan failed: {message}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(
        "Live scan: " + ", ".join(f"{key}={value}" for key, value in result.run.counts.items())
    )
    typer.echo(f"Status: {result.run.status.value}; run ID: {result.run.id}")
    typer.echo(f"Reports: {config.runtime.report_dir / str(result.run.id)}")
    if result.run.status.value == "FAILED":
        raise typer.Exit(code=1)


@app.command("doctor")
def doctor_command(
    config_path: Annotated[
        Path,
        typer.Option("--config", help="Production YAML config path"),
    ] = Path("config.production.yaml"),
    send_telegram_test: Annotated[
        bool,
        typer.Option(
            "--send-telegram-test",
            help="Send one explicit Telegram connectivity message",
        ),
    ] = False,
) -> None:
    """Validate production configuration and external dependencies without scanning."""
    import os

    from htf_scanner.production.doctor import run_doctor

    try:
        config = load_config(config_path)
        result = run_doctor(
            config,
            os.environ,
            send_telegram_test=send_telegram_test,
        )
    except Exception as error:
        message = str(error) if str(error) else error.__class__.__name__
        typer.echo(f"Doctor failed: {message}", err=True)
        raise typer.Exit(code=1) from error
    for check in result.checks:
        typer.echo(f"OK: {check}")
    typer.echo(
        f"Doctor passed: provider={result.provider}, markets={result.markets}, "
        f"server_time={result.server_time}"
    )


def _load_h4_inputs(
    symbol: str,
    start: datetime,
    end: datetime | None,
    offline: bool,
    d1_path: Path | None,
    h4_path: Path | None,
    config: AppConfig,
) -> tuple[list[Candle], list[Candle]]:
    from htf_scanner.data.file_reader import read_candle_file

    start_at = _as_utc(start)
    end_at = _as_utc(end) if end is not None else datetime.now(UTC)
    file_cache = CandleFileCache(config.storage.candle_cache_dir)
    d1 = read_candle_file(d1_path) if d1_path is not None else file_cache.read(symbol, "1d")
    h4 = read_candle_file(h4_path) if h4_path is not None else file_cache.read(symbol, "4h")
    if not offline and (d1_path is None or h4_path is None):
        engine = create_database_engine(config.storage.database_url)
        repository = CandleRepository(engine)
        with BinanceRestClient() as client:
            downloader = CandleDownloader(client, repository, file_cache)
            if d1_path is None:
                d1 = downloader.download(symbol, "1d", start_at, end_at)
            if h4_path is None:
                h4 = downloader.download(symbol, "4h", start_at, end_at)
        engine.dispose()
    if end is None and d1 and h4:
        end_at = max(d1[-1].close_time, h4[-1].close_time) + timedelta(milliseconds=1)

    def selected(items: list[Candle]) -> list[Candle]:
        return [item for item in items if start_at <= item.open_time < end_at]

    selected_d1 = selected(d1)
    selected_h4 = selected(h4)
    if not selected_d1:
        raise typer.BadParameter("no D1 candles found for the requested range")
    if not selected_h4:
        raise typer.BadParameter("no H4 candles found for the requested range")
    return selected_d1, selected_h4


def _persist_h4_result(
    repository: AnalysisRepository,
    result: SymbolAnalysisResult,
    run_id: str,
) -> None:
    repository.upsert_fvgs(result.d1.fvgs + result.h4.fvgs)
    repository.upsert_swings(result.d1.swings + result.h4.swings)
    repository.upsert_structure_breaks(result.d1.structure_breaks + result.h4.structure_breaks)
    repository.upsert_structure_promotions(result.d1.structure_promotions)
    repository.upsert_displacements(result.d1.displacements + result.h4.displacements)
    repository.upsert_liquidity_interactions(result.d1.liquidity_interactions)
    repository.upsert_liquidity_contexts(result.d1.liquidity_contexts)
    repository.upsert_liquidity_sequences(result.d1.liquidity_sequences)
    repository.upsert_setup_candidates(result.d1.setup_candidates)
    repository.upsert_merged_candidates(result.d1.merged_candidates)
    repository.upsert_setups(result.d1.setups)
    repository.upsert_setup_transitions(result.d1.setup_transitions)
    repository.upsert_rejected_candidates(result.d1.rejected_candidates)
    repository.upsert_events(result.d1.events)
    repository.upsert_h4_touch_phases(result.h4.touch_phases, run_id)
    repository.upsert_reactions(result.h4.reactions, run_id)
    repository.upsert_h4_candidates(result.h4.reaction_candidates, run_id)
    repository.upsert_h4_merged_candidates(result.h4.merged_candidates, run_id)
    repository.upsert_h4_transitions(result.h4.transitions, run_id)
    repository.upsert_reaction_outcomes(result.outcomes.outcomes, run_id)
    repository.upsert_reaction_target_outcomes(result.outcomes.target_outcomes, run_id)


def _write_h4_reports(
    h4_candles: list[Candle],
    result: SymbolAnalysisResult,
    report_dir: Path,
) -> dict[str, Path]:
    from htf_scanner.reports.charts import plot_h4_reaction_debug
    from htf_scanner.reports.exports import export_domain_csv, export_json

    candles = h4_candles
    export_domain_csv(result.h4.touch_phases, report_dir / "h4_touch_phases.csv", ["id"])
    reactions_path = export_domain_csv(result.h4.reactions, report_dir / "h4_reactions.csv", ["id"])
    export_domain_csv(
        result.h4.reaction_candidates,
        report_dir / "h4_reaction_candidates.csv",
        ["id"],
    )
    export_domain_csv(
        result.h4.rejected_candidates,
        report_dir / "h4_rejected_candidates.csv",
        ["id"],
    )
    export_domain_csv(
        result.h4.merged_candidates,
        report_dir / "h4_merged_candidates.csv",
        ["id"],
    )
    export_domain_csv(
        result.h4.transitions,
        report_dir / "h4_reaction_transitions.csv",
        ["id"],
    )
    export_domain_csv(
        result.outcomes.outcomes,
        report_dir / "reaction_outcomes.csv",
        ["id"],
    )
    export_domain_csv(
        result.outcomes.target_outcomes,
        report_dir / "reaction_target_outcomes.csv",
        ["id"],
    )
    diagnostics_path = export_json(
        {
            "counts": {
                "h4_candles": len(candles),
                "touch_phases": len(result.h4.touch_phases),
                "reactions": len(result.h4.reactions),
                "confirmed": sum(item.confirmed_at is not None for item in result.h4.reactions),
                "outcomes": len(result.outcomes.outcomes),
            },
            "data_quality": result.h4.diagnostics,
            "outcome_diagnostics": result.outcomes.diagnostics,
            "reactions": [item.model_dump(mode="json") for item in result.h4.reactions],
            "rejected_candidates": [
                item.model_dump(mode="json") for item in result.h4.rejected_candidates
            ],
        },
        report_dir / "h4_diagnostics.json",
    )
    chart_path = plot_h4_reaction_debug(
        candles,
        result.d1.fvgs,
        result.h4.reactions,
        result.h4.touch_phases,
        result.h4.structure_breaks,
        result.h4.displacements,
        result.outcomes.target_outcomes,
        report_dir / "h4_reactions.png",
    )
    return {"reactions": reactions_path, "diagnostics": diagnostics_path, "chart": chart_path}


def _write_batch_reports(result: BatchUniverseResult, report_dir: Path) -> None:
    from htf_scanner.domain.enums import SetupStatus
    from htf_scanner.reports.exports import export_domain_csv, export_json, export_records_csv

    export_records_csv(
        [{"metric": key, "value": value} for key, value in result.run.counts.items()],
        report_dir / "universe_summary.csv",
        ["metric", "value"],
    )
    export_domain_csv(result.symbol_runs, report_dir / "symbol_run_summary.csv", ["id"])
    active_setups = [
        setup
        for symbol in sorted(result.analyses)
        for setup in result.analyses[symbol].d1.setups
        if setup.status == SetupStatus.ACTIVE
    ]
    confirmed = [
        reaction
        for symbol in sorted(result.analyses)
        for reaction in result.analyses[symbol].h4.reactions
        if reaction.confirmed_at is not None
    ]
    outcomes = [
        outcome
        for symbol in sorted(result.analyses)
        for outcome in result.analyses[symbol].outcomes.outcomes
    ]
    export_domain_csv(active_setups, report_dir / "active_d1_setups.csv", ["id"])
    export_domain_csv(confirmed, report_dir / "confirmed_h4_reactions.csv", ["id"])
    export_domain_csv(outcomes, report_dir / "reaction_outcome_summary.csv", ["id"])
    quality_records: list[dict[str, str | float | int | bool | None]] = [
        {"symbol": symbol, "diagnostic": diagnostic}
        for symbol in sorted(result.analyses)
        for diagnostic in result.analyses[symbol].h4.diagnostics
    ]
    quality_records.extend(
        {"symbol": symbol, "diagnostic": error} for symbol, error in sorted(result.errors.items())
    )
    export_records_csv(
        quality_records,
        report_dir / "data_quality_errors.csv",
        ["symbol", "diagnostic"],
    )
    export_json(
        {
            "run": result.run.model_dump(mode="json"),
            "symbols": [item.model_dump(mode="json") for item in result.symbol_runs],
        },
        report_dir / "run_manifest.json",
    )


def _as_utc(timestamp: datetime) -> datetime:
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)
