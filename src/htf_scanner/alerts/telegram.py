import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from htf_scanner.config import RetryConfig, TelegramConfig
from htf_scanner.domain.production import ScannerEvent


class TelegramDeliveryError(RuntimeError):
    pass


class TelegramSender:
    def __init__(
        self,
        config: TelegramConfig,
        retry: RetryConfig,
        bot_token: str,
        chat_id: str,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not bot_token or not chat_id:
            raise ValueError("Telegram bot token and chat id are required")
        self._config = config
        self._retry = retry
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=config.api_base_url,
            timeout=config.timeout_seconds,
        )
        self._sleep = sleep

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def send(self, event: ScannerEvent, chart: Path | None = None) -> str | None:
        text = render_event(event)
        if chart is not None and chart.exists():
            try:
                return self._request(
                    "sendPhoto",
                    data={
                        "chat_id": self._chat_id,
                        "caption": text,
                        "parse_mode": self._config.parse_mode,
                    },
                    files={"photo": (chart.name, chart.read_bytes(), "image/png")},
                )
            except TelegramDeliveryError:
                # Text fallback keeps the event deliverable when media upload fails.
                pass
        return self._request(
            "sendMessage",
            data={
                "chat_id": self._chat_id,
                "text": text,
                "parse_mode": self._config.parse_mode,
            },
        )

    def send_test_message(self) -> str | None:
        return self._request(
            "sendMessage",
            data={
                "chat_id": self._chat_id,
                "text": "*HTF Scanner doctor OK*",
                "parse_mode": self._config.parse_mode,
            },
        )

    def _request(
        self,
        method: str,
        data: dict[str, str],
        files: dict[str, tuple[str, bytes, str]] | None = None,
    ) -> str | None:
        error: Exception | None = None
        for attempt in range(self._retry.attempts):
            try:
                response = self._client.post(
                    f"/bot{self._bot_token}/{method}", data=data, files=files
                )
                response.raise_for_status()
                payload: Any = response.json()
                if not isinstance(payload, dict) or payload.get("ok") is not True:
                    raise TelegramDeliveryError("Telegram returned an unsuccessful payload")
                result = payload.get("result")
                if isinstance(result, dict) and result.get("message_id") is not None:
                    return str(result["message_id"])
                return None
            except (httpx.HTTPError, TelegramDeliveryError) as caught:
                error = caught
                if attempt + 1 < self._retry.attempts:
                    delay = min(
                        self._retry.maximum_backoff_seconds,
                        self._retry.initial_backoff_seconds * (2**attempt),
                    )
                    self._sleep(delay)
        raise TelegramDeliveryError(str(error) if error else "Telegram delivery failed")


def render_event(event: ScannerEvent) -> str:
    payload = event.payload
    lines = [
        f"*{escape_markdown(event.event_type.value)}*",
        f"Symbol: `{escape_markdown(event.symbol)}`",
        f"Side: `{escape_markdown(event.side.value)}`",
    ]
    for label, key in (
        ("Context", "context"),
        ("Score", "quality_score"),
        ("FVG", "fvg_id"),
        ("Invalidation", "invalidation_price"),
        ("Reason", "reason"),
    ):
        value = payload.get(key)
        if value is not None:
            lines.append(f"{label}: `{escape_markdown(str(value))}`")
    lines.extend(
        [
            f"Formed: `{escape_markdown(event.formed_at.isoformat())}`",
            f"Known: `{escape_markdown(event.known_at.isoformat())}`",
        ]
    )
    return "\n".join(lines)


def escape_markdown(value: str) -> str:
    reserved = "_[]()~`>#+-=|{}.!*\\"
    return "".join(f"\\{char}" if char in reserved else char for char in value)
