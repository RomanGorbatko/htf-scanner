import csv
import json
from pathlib import Path
from typing import Any

from htf_scanner.domain.production import (
    AlertDelivery,
    LiveScannerRun,
    LiveSymbolRun,
    MarketInfo,
)


def write_live_reports(
    output_dir: Path,
    run: LiveScannerRun,
    universe: list[MarketInfo],
    symbols: list[LiveSymbolRun],
    deliveries: list[AlertDelivery],
    data_quality: list[dict[str, Any]],
) -> dict[str, Path]:
    run_dir = output_dir / str(run.id)
    run_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "manifest": run_dir / "run_manifest.json",
        "universe": run_dir / "universe_snapshot.csv",
        "run_summary": run_dir / "run_summary.csv",
        "symbol_summary": run_dir / "symbol_summary.csv",
        "alerts_sent": run_dir / "alerts_sent.csv",
        "alerts_pending": run_dir / "alerts_pending.csv",
        "data_quality": run_dir / "data_quality.csv",
        "runtime_metrics": run_dir / "runtime_metrics.csv",
    }
    paths["manifest"].write_text(
        json.dumps(run.model_dump(mode="json"), sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_models(paths["universe"], universe)
    _write_models(paths["run_summary"], [run])
    _write_models(paths["symbol_summary"], symbols)
    _write_models(
        paths["alerts_sent"], [item for item in deliveries if item.status.value == "SENT"]
    )
    _write_models(
        paths["alerts_pending"], [item for item in deliveries if item.status.value != "SENT"]
    )
    _write_dicts(paths["data_quality"], data_quality)
    _write_dicts(
        paths["runtime_metrics"],
        [
            {"scope": "run", "name": key, "value_ms": value}
            for key, value in sorted(run.timings_ms.items())
        ]
        + [
            {"scope": item.symbol, "name": key, "value_ms": value}
            for item in symbols
            for key, value in sorted(item.timings_ms.items())
        ],
    )
    return paths


def _write_models(path: Path, items: list[Any]) -> None:
    _write_dicts(path, [item.model_dump(mode="json") for item in items])


def _write_dicts(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        if not fieldnames:
            handle.write("")
            return
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value, sort_keys=True)
                    if isinstance(value, (dict, list))
                    else value
                    for key, value in row.items()
                }
            )
