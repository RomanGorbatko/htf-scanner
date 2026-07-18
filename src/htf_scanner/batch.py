import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter_ns
from uuid import NAMESPACE_URL, uuid5

from htf_scanner.config import AppConfig
from htf_scanner.data.cache import CandleFileCache
from htf_scanner.domain.enums import BatchRunStatus
from htf_scanner.domain.run import BatchRun, BatchSymbolRun
from htf_scanner.pipeline import SymbolAnalysisResult, analyze_symbol


@dataclass(frozen=True)
class BatchUniverseResult:
    run: BatchRun
    symbol_runs: list[BatchSymbolRun]
    analyses: dict[str, SymbolAnalysisResult]
    errors: dict[str, str]
    runtime_measurements_ms: dict[str, float]


def scan_offline_universe(
    symbols: list[str],
    cache: CandleFileCache,
    config: AppConfig,
    config_hash: str,
) -> BatchUniverseResult:
    ordered_symbols = sorted({symbol.strip().upper() for symbol in symbols if symbol.strip()})
    if not ordered_symbols:
        raise ValueError("batch scan requires at least one symbol")
    batch_id = uuid5(
        NAMESPACE_URL,
        f"offline-batch:{','.join(ordered_symbols)}:{config_hash}",
    )
    analyses: dict[str, SymbolAnalysisResult] = {}
    errors: dict[str, str] = {}
    symbol_runs: list[BatchSymbolRun] = []
    runtime_measurements_ms: dict[str, float] = {}
    logical_times: list[datetime] = []
    for symbol in ordered_symbols:
        runtime_started = perf_counter_ns()
        d1 = cache.read(symbol, "1d")
        h4 = cache.read(symbol, "4h")
        available = d1 + h4
        started_at = min(
            (item.open_time for item in available), default=datetime(1970, 1, 1, tzinfo=UTC)
        )
        completed_at = max(
            (item.close_time for item in available), default=datetime(1970, 1, 1, tzinfo=UTC)
        )
        logical_times.extend([started_at, completed_at])
        status = BatchRunStatus.COMPLETED
        error: str | None = None
        setup_count = reaction_count = outcome_count = 0
        try:
            if len(d1) < config.batch_scan.minimum_d1_candles:
                raise ValueError(
                    f"insufficient D1 warm-up: {len(d1)} < {config.batch_scan.minimum_d1_candles}"
                )
            if len(h4) < config.batch_scan.minimum_h4_candles:
                raise ValueError(
                    f"insufficient H4 warm-up: {len(h4)} < {config.batch_scan.minimum_h4_candles}"
                )
            analysis = analyze_symbol(d1, h4, config, config_hash, strict_data=True)
            analyses[symbol] = analysis
            setup_count = len(analysis.d1.setups)
            reaction_count = len(analysis.h4.reactions)
            outcome_count = len(analysis.outcomes.outcomes)
        except (OSError, ValueError) as exc:
            status = BatchRunStatus.FAILED
            error = str(exc)
            errors[symbol] = error
            if not config.batch_scan.continue_on_symbol_error:
                raise
        symbol_runs.append(
            BatchSymbolRun(
                id=uuid5(NAMESPACE_URL, f"batch-symbol:{batch_id}:{symbol}"),
                batch_run_id=batch_id,
                symbol=symbol,
                status=status,
                started_at=started_at,
                completed_at=completed_at,
                runtime_ms=0,
                d1_candles=len(d1),
                h4_candles=len(h4),
                setup_count=setup_count,
                reaction_count=reaction_count,
                outcome_count=outcome_count,
                error=error,
            )
        )
        runtime_measurements_ms[symbol] = (perf_counter_ns() - runtime_started) / 1_000_000
    manifest_payload = {
        "config_hash": config_hash,
        "symbols": ordered_symbols,
        "symbol_runs": [
            item.model_dump(mode="json", exclude={"started_at", "completed_at", "runtime_ms"})
            for item in symbol_runs
        ],
    }
    manifest_hash = hashlib.sha256(
        json.dumps(manifest_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    failures = len(errors)
    status = (
        BatchRunStatus.COMPLETED
        if failures == 0
        else BatchRunStatus.FAILED
        if failures == len(ordered_symbols)
        else BatchRunStatus.PARTIAL
    )
    run = BatchRun(
        id=batch_id,
        config_hash=config_hash,
        symbols=ordered_symbols,
        started_at=min(logical_times),
        completed_at=max(logical_times),
        status=status,
        manifest_hash=manifest_hash,
        counts={
            "symbols": len(ordered_symbols),
            "completed_symbols": len(ordered_symbols) - failures,
            "failed_symbols": failures,
            "setups": sum(item.setup_count for item in symbol_runs),
            "reactions": sum(item.reaction_count for item in symbol_runs),
            "outcomes": sum(item.outcome_count for item in symbol_runs),
        },
    )
    return BatchUniverseResult(
        run=run,
        symbol_runs=symbol_runs,
        analyses=analyses,
        errors=errors,
        runtime_measurements_ms=runtime_measurements_ms,
    )
