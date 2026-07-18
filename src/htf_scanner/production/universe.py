from datetime import datetime

from htf_scanner.config import AppConfig
from htf_scanner.domain.production import MarketInfo


def select_universe(
    markets: list[MarketInfo], config: AppConfig, now: datetime
) -> list[MarketInfo]:
    include = {item.upper() for item in config.universe.include}
    exclude = {item.upper() for item in config.universe.exclude}
    selected = [
        market
        for market in markets
        if market.quote_asset == config.exchange.quote_asset.upper()
        and market.contract_type == config.exchange.contract_type
        and (market.active or not config.universe.active_only)
        and (now - market.onboard_at).days >= config.universe.minimum_history_days
        and market.quote_volume_24h >= config.universe.minimum_quote_volume_24h
        and market.symbol not in exclude
        and (not include or market.symbol in include)
    ]
    selected.sort(key=lambda item: (-item.quote_volume_24h, item.symbol))
    if config.universe.maximum_symbols is not None:
        selected = selected[: config.universe.maximum_symbols]
    return sorted(selected, key=lambda item: item.symbol)
