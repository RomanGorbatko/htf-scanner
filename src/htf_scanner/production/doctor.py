from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from htf_scanner.alerts.telegram import TelegramSender
from htf_scanner.config import (
    AppConfig,
    MarketDataConfig,
    telegram_environment_names_valid,
)
from htf_scanner.data.factory import create_market_data_provider
from htf_scanner.data.provider import MarketDataProvider
from htf_scanner.storage.database import create_database_engine


class DoctorError(RuntimeError):
    pass


@dataclass(frozen=True)
class DoctorResult:
    checks: list[str]
    provider: str
    server_time: str
    markets: int
    telegram_test_sent: bool


ProviderFactory = Callable[[MarketDataConfig], MarketDataProvider]


def run_doctor(
    config: AppConfig,
    environment: Mapping[str, str],
    *,
    send_telegram_test: bool = False,
    provider_factory: ProviderFactory = create_market_data_provider,
) -> DoctorResult:
    checks = ["configuration parsed"]
    if config.telegram.enabled and not telegram_environment_names_valid(config.telegram):
        raise DoctorError(
            "telegram.bot_token_env and telegram.chat_id_env must contain environment "
            "variable names, not credential values"
        )
    paths = _runtime_paths(config)
    for label, path in paths:
        _assert_writable_directory(path, label)
        checks.append(f"{label} writable: {path}")

    engine = create_database_engine(config.storage.database_url)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
        checks.append("database initialized")
    finally:
        engine.dispose()

    provider = provider_factory(config.market_data)
    try:
        server_time = provider.server_time()
        if server_time.utcoffset() != timedelta(0):
            raise DoctorError("exchange server time is not UTC")
        markets = provider.discover_markets()
        if not markets:
            raise DoctorError("market discovery returned no markets")
        checks.extend(
            [
                f"provider supported: {config.market_data.provider}",
                f"exchange reachable: {server_time.isoformat()}",
                f"markets discovered: {len(markets)}",
            ]
        )
    finally:
        provider.close()

    telegram_test_sent = False
    if config.telegram.enabled:
        token = environment.get(config.telegram.bot_token_env, "")
        chat_id = environment.get(config.telegram.chat_id_env, "")
        if not token or not chat_id:
            raise DoctorError(
                "Telegram is enabled but required credential environment variables are missing"
            )
        checks.append("Telegram credentials present")
        if send_telegram_test:
            sender = TelegramSender(config.telegram, config.retry, token, chat_id)
            try:
                sender.send_test_message()
            finally:
                sender.close()
            telegram_test_sent = True
            checks.append("Telegram test message sent")
    elif send_telegram_test:
        raise DoctorError("cannot send a Telegram test while telegram.enabled is false")

    return DoctorResult(
        checks=checks,
        provider=config.market_data.provider,
        server_time=server_time.isoformat(),
        markets=len(markets),
        telegram_test_sent=telegram_test_sent,
    )


def _runtime_paths(config: AppConfig) -> list[tuple[str, Path]]:
    if not config.storage.database_url.startswith("sqlite:///"):
        raise DoctorError("production doctor currently requires a sqlite:/// database URL")
    database = Path(config.storage.database_url.removeprefix("sqlite:///"))
    return [
        ("database directory", database.parent),
        ("state directory", config.runtime.state_dir),
        ("candle cache directory", config.storage.candle_cache_dir),
        ("live report directory", config.runtime.report_dir),
        ("report directory", config.reports.output_dir),
        ("lock directory", config.scheduler.lock_path.parent),
    ]


def _assert_writable_directory(path: Path, label: str) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".htf-scanner-doctor-{uuid4().hex}"
        probe.write_text("ok", encoding="ascii")
        probe.unlink()
    except OSError as error:
        raise DoctorError(f"{label} is not writable: {path}: {error}") from error
