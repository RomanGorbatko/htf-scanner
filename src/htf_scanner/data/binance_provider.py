from datetime import UTC, datetime, timedelta
from typing import Any

from htf_scanner.data.binance_rest import BinanceDataError, BinanceRestClient
from htf_scanner.data.provider import MarketDataProvider
from htf_scanner.domain.candle import Candle
from htf_scanner.domain.production import ExchangeMetadata, MarketInfo


class BinanceMarketDataProvider(MarketDataProvider):
    """Binance USD-M details stay behind the provider boundary."""

    def __init__(
        self,
        base_url: str = "https://fapi.binance.com",
        timeout_seconds: float = 30.0,
        client: BinanceRestClient | None = None,
    ) -> None:
        self._owns_client = client is None
        self._client = client or BinanceRestClient(base_url, timeout_seconds)

    def __enter__(self) -> "BinanceMarketDataProvider":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def server_time(self) -> datetime:
        payload = self._client.request_json("/fapi/v1/time")
        if not isinstance(payload, dict) or "serverTime" not in payload:
            raise BinanceDataError("Binance time response is invalid")
        return datetime.fromtimestamp(int(payload["serverTime"]) / 1000, tz=UTC)

    def discover_markets(self) -> list[MarketInfo]:
        exchange = self._client.request_json("/fapi/v1/exchangeInfo")
        tickers = self._client.request_json("/fapi/v1/ticker/24hr")
        if not isinstance(exchange, dict) or not isinstance(exchange.get("symbols"), list):
            raise BinanceDataError("Binance exchangeInfo response is invalid")
        if not isinstance(tickers, list):
            raise BinanceDataError("Binance ticker response is invalid")
        volumes = {
            str(item.get("symbol", "")).upper(): float(item.get("quoteVolume", 0.0))
            for item in tickers
            if isinstance(item, dict)
        }
        markets = [self._parse_market(item, volumes) for item in exchange["symbols"]]
        return sorted(markets, key=lambda item: item.symbol)

    @staticmethod
    def _parse_market(payload: Any, volumes: dict[str, float]) -> MarketInfo:
        if not isinstance(payload, dict):
            raise BinanceDataError("Binance market row is invalid")
        symbol = str(payload.get("symbol", "")).upper()
        onboard_ms = int(payload.get("onboardDate", 0))
        return MarketInfo(
            symbol=symbol,
            quote_asset=str(payload.get("quoteAsset", "")).upper(),
            contract_type=str(payload.get("contractType", "")),
            active=payload.get("status") == "TRADING",
            onboard_at=datetime.fromtimestamp(onboard_ms / 1000, tz=UTC),
            quote_volume_24h=max(0.0, volumes.get(symbol, 0.0)),
        )

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        return self._client.fetch_klines(symbol, timeframe, start, end, now=self.server_time())

    def fetch_latest_closed_candle(self, symbol: str, timeframe: str) -> Candle | None:
        interval = _interval(timeframe)
        now = self.server_time()
        candles = self._client.fetch_klines(
            symbol,
            timeframe,
            now - interval * 3,
            now,
            now=now,
        )
        return candles[-1] if candles else None

    def exchange_metadata(self) -> ExchangeMetadata:
        markets = self.discover_markets()
        return ExchangeMetadata(
            provider="binance",
            server_time=self.server_time(),
            markets=len(markets),
        )


def _interval(timeframe: str) -> timedelta:
    try:
        return {"1d": timedelta(days=1), "4h": timedelta(hours=4)}[timeframe]
    except KeyError as error:
        raise ValueError(f"unsupported timeframe: {timeframe}") from error
