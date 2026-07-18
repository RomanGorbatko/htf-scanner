import csv
import json
from pathlib import Path

from htf_scanner.domain.candle import Candle


def read_candle_file(path: Path) -> list[Candle]:
    if path.suffix.lower() == ".jsonl":
        with path.open(encoding="utf-8") as source:
            return [Candle.model_validate_json(line) for line in source if line.strip()]
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8", newline="") as source:
            rows = list(csv.DictReader(source))
        return [Candle.model_validate(_normalize_row(row)) for row in rows]
    raise ValueError(f"unsupported candle file format: {path.suffix}")


def _normalize_row(row: dict[str, str | None]) -> dict[str, object]:
    normalized: dict[str, object] = {
        key: value for key, value in row.items() if value not in (None, "")
    }
    for key in ("trades",):
        if key in normalized:
            normalized[key] = int(str(normalized[key]))
    if "is_closed" in normalized:
        normalized["is_closed"] = str(normalized["is_closed"]).lower() in {"1", "true", "yes"}
    for key in ("features", "payload"):
        if key in normalized:
            normalized[key] = json.loads(str(normalized[key]))
    return normalized
