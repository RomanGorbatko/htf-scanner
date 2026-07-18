import csv
import json
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel

from htf_scanner.domain.fvg import FairValueGap

FVG_COLUMNS = [
    "id",
    "symbol",
    "timeframe",
    "side",
    "formed_at",
    "known_at",
    "source_candle_time",
    "lower",
    "upper",
    "midpoint",
    "size",
    "size_atr",
    "status",
    "fill_ratio",
    "first_touch_at",
    "first_25_fill_at",
    "midpoint_fill_at",
    "first_75_fill_at",
    "full_fill_at",
    "invalidated_at",
    "expired_at",
]


def export_fvgs_csv(fvgs: list[FairValueGap], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=FVG_COLUMNS)
        writer.writeheader()
        for fvg in fvgs:
            record = fvg.model_dump(mode="json")
            writer.writerow({column: record.get(column) for column in FVG_COLUMNS})
    return path


def export_domain_csv(items: Sequence[BaseModel], path: Path, empty_columns: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    records = [_csv_record(item) for item in items]
    columns = list(dict.fromkeys(key for record in records for key in record)) or empty_columns
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        writer.writerows(records)
    return path


def _csv_record(item: BaseModel) -> dict[str, str | float | int | bool | None]:
    raw = item.model_dump(mode="json")
    return {
        key: json.dumps(value, sort_keys=True, separators=(",", ":"))
        if isinstance(value, (dict, list))
        else value
        for key, value in raw.items()
    }


def export_json(payload: object, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return path


def export_records_csv(
    records: Sequence[dict[str, str | float | int | bool | None]],
    path: Path,
    empty_columns: list[str],
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = list(dict.fromkeys(key for record in records for key in record)) or empty_columns
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        writer.writerows(records)
    return path
