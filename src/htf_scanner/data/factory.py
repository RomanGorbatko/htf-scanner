from htf_scanner.config import MarketDataConfig
from htf_scanner.data.provider import MarketDataProvider


class ProviderConfigurationError(ValueError):
    pass


def create_market_data_provider(config: MarketDataConfig) -> MarketDataProvider:
    provider = config.provider.strip().lower()
    if provider == "binance":
        from htf_scanner.data.binance_provider import BinanceMarketDataProvider

        return BinanceMarketDataProvider(
            base_url=config.base_url,
            timeout_seconds=config.timeout_seconds,
        )
    raise ProviderConfigurationError(
        f"unsupported market_data.provider: {config.provider!r}; supported providers: binance"
    )
