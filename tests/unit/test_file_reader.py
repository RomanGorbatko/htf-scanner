import csv
from pathlib import Path

import pytest

from htf_scanner.data.file_reader import read_candle_file
from tests.unit.test_h4_reaction_engine import h4


def test_jsonl_and_csv_candle_files_are_typed(tmp_path: Path) -> None:
    candle = h4(0, "10", "11", "9", "10")
    jsonl = tmp_path / "candles.jsonl"
    jsonl.write_text(candle.model_dump_json() + "\n\n", encoding="utf-8")
    assert read_candle_file(jsonl) == [candle]
    csv_path = tmp_path / "candles.csv"
    record = candle.model_dump(mode="json")
    with csv_path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(record))
        writer.writeheader()
        writer.writerow(record)
    assert read_candle_file(csv_path) == [candle]


def test_unknown_candle_file_extension_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsupported candle file format"):
        read_candle_file(tmp_path / "candles.txt")
