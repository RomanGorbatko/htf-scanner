from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from htf_scanner.data.binance_rest import (
    KLINE_LIMIT,
    BinanceDataError,
    BinanceRestClient,
    validate_candles,
)
from tests.conftest import make_candle


def _row(open_time: datetime, interval: timedelta = timedelta(hours=4)) -> list[Any]:
    open_ms = int(open_time.timestamp() * 1000)
    close_ms = int((open_time + interval).timestamp() * 1000) - 1
    return [open_ms, "1", "2", "0.5", "1.5", "10", close_ms, "15", 4, "0", "0", "0"]


def test_binance_client_paginates_and_returns_closed_candles() -> None:
    first_open = datetime(2025, 1, 1, tzinfo=UTC)
    rows = [_row(first_open + timedelta(hours=4 * index)) for index in range(KLINE_LIMIT + 1)]
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        payload = rows[:KLINE_LIMIT] if calls == 1 else rows[KLINE_LIMIT:]
        return httpx.Response(200, json=payload, request=request)

    http_client = httpx.Client(
        base_url="https://fapi.binance.com", transport=httpx.MockTransport(handler)
    )
    client = BinanceRestClient(client=http_client)

    candles = client.fetch_klines(
        "testusdt",
        "4h",
        first_open,
        first_open + timedelta(hours=4 * len(rows)),
        now=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert calls == 2
    assert len(candles) == KLINE_LIMIT + 1
    assert candles[0].symbol == "TESTUSDT"


def test_validation_deduplicates_and_rejects_missing_or_misaligned_candles() -> None:
    first = make_candle(0, "1", "2", "0.5", "1.5")
    assert validate_candles([first, first], "1d") == [first]

    with pytest.raises(BinanceDataError, match="missing"):
        validate_candles([first, make_candle(2, "1", "2", "0.5", "1.5")], "1d")
    with pytest.raises(BinanceDataError, match="timeframe"):
        validate_candles([first], "4h")
    with pytest.raises(ValueError, match="unsupported"):
        validate_candles([], "1h")


def test_client_validates_request_and_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "bad payload"}, request=request)

    http_client = httpx.Client(
        base_url="https://example.test", transport=httpx.MockTransport(handler)
    )
    client = BinanceRestClient(client=http_client)
    start = datetime(2025, 1, 1, tzinfo=UTC)

    with pytest.raises(ValueError, match="after start"):
        client.fetch_klines("TESTUSDT", "1d", start, start)
    with pytest.raises(BinanceDataError, match="must be a list"):
        client.fetch_klines("TESTUSDT", "1d", start, start + timedelta(days=1))
