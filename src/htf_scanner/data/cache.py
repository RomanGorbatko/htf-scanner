import json
from pathlib import Path

from htf_scanner.domain.candle import Candle


class CandleFileCache:
    def __init__(self, root: Path) -> None:
        self._root = root

    def write(self, symbol: str, timeframe: str, candles: list[Candle]) -> Path:
        path = self._path(symbol, timeframe)
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = {candle.open_time: candle for candle in self.read(symbol, timeframe)}
        existing.update({candle.open_time: candle for candle in candles})
        with path.open("w", encoding="utf-8") as output:
            for candle in sorted(existing.values(), key=lambda item: item.open_time):
                output.write(candle.model_dump_json() + "\n")
        return path

    def read(self, symbol: str, timeframe: str) -> list[Candle]:
        path = self._path(symbol, timeframe)
        if not path.exists():
            return []
        candles: list[Candle] = []
        with path.open(encoding="utf-8") as source:
            for line in source:
                if line.strip():
                    candles.append(Candle.model_validate(json.loads(line)))
        return candles

    def _path(self, symbol: str, timeframe: str) -> Path:
        return self._root / symbol.upper() / f"{timeframe}.jsonl"
