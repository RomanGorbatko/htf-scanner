from datetime import UTC, datetime
from decimal import Decimal
from itertools import pairwise
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from htf_scanner.domain.candle import Candle

KLINE_LIMIT = 1500


class BinanceDataError(ValueError):
    pass


class BinanceRestClient:
    def __init__(
        self,
        base_url: str = "https://fapi.binance.com",
        timeout_seconds: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.Client(base_url=base_url, timeout=timeout_seconds)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "BinanceRestClient":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def _request_page(self, params: dict[str, Any]) -> list[list[Any]]:
        response = self._client.get("/fapi/v1/klines", params=params)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise BinanceDataError("Binance kline response must be a list")
        return payload

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def request_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        response = self._client.get(path, params=params)
        response.raise_for_status()
        return response.json()

    def fetch_klines(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        now: datetime | None = None,
    ) -> list[Candle]:
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("start and end must be timezone-aware")
        if end <= start:
            raise ValueError("end must be after start")
        closed_before = (now or datetime.now(UTC)).astimezone(UTC)
        cursor_ms = int(start.timestamp() * 1000)
        end_ms = int(min(end, closed_before).timestamp() * 1000)
        candles: list[Candle] = []
        while cursor_ms < end_ms:
            page = self._request_page(
                {
                    "symbol": symbol.upper(),
                    "interval": timeframe,
                    "startTime": cursor_ms,
                    "endTime": end_ms - 1,
                    "limit": KLINE_LIMIT,
                }
            )
            if not page:
                break
            parsed = [self._parse_kline(symbol, timeframe, row, closed_before) for row in page]
            candles.extend(
                candle for candle in parsed if candle.is_closed and candle.open_time < end
            )
            next_cursor = int(page[-1][0]) + 1
            if next_cursor <= cursor_ms:
                raise BinanceDataError("Binance pagination did not advance")
            cursor_ms = next_cursor
            if len(page) < KLINE_LIMIT:
                break
        return validate_candles(candles, timeframe)

    @staticmethod
    def _parse_kline(
        symbol: str,
        timeframe: str,
        row: list[Any],
        closed_before: datetime,
    ) -> Candle:
        if len(row) < 11:
            raise BinanceDataError("Binance kline row has fewer than 11 fields")
        close_time = datetime.fromtimestamp(int(row[6]) / 1000, tz=UTC)
        return Candle(
            symbol=symbol,
            timeframe=timeframe,
            open_time=datetime.fromtimestamp(int(row[0]) / 1000, tz=UTC),
            close_time=close_time,
            open=Decimal(str(row[1])),
            high=Decimal(str(row[2])),
            low=Decimal(str(row[3])),
            close=Decimal(str(row[4])),
            volume=Decimal(str(row[5])),
            quote_volume=Decimal(str(row[7])),
            trades=int(row[8]),
            is_closed=close_time <= closed_before,
        )


def validate_candles(candles: list[Candle], timeframe: str) -> list[Candle]:
    deduplicated = {candle.open_time: candle for candle in candles}
    ordered = sorted(deduplicated.values(), key=lambda candle: candle.open_time)
    interval_ms = {"1d": 86_400_000, "4h": 14_400_000}.get(timeframe)
    if interval_ms is None:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    for candle in ordered:
        if candle.timeframe != timeframe:
            raise BinanceDataError("candle timeframe does not match requested timeframe")
        if timeframe == "1d" and (candle.open_time.hour, candle.open_time.minute) != (0, 0):
            raise BinanceDataError("D1 candle is not aligned to the UTC exchange boundary")
        if timeframe == "4h" and (candle.open_time.hour % 4, candle.open_time.minute) != (0, 0):
            raise BinanceDataError("H4 candle is not aligned to the UTC exchange boundary")
    for previous, current in pairwise(ordered):
        delta_ms = int((current.open_time - previous.open_time).total_seconds() * 1000)
        if delta_ms != interval_ms:
            raise BinanceDataError(
                f"missing or misaligned {timeframe} candle between "
                f"{previous.open_time.isoformat()} and {current.open_time.isoformat()}"
            )
    return ordered
