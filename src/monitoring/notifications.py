"""External notification adapters for operational events."""

from typing import Any

import requests


class NotificationError(RuntimeError):
    """Raised when an external notification cannot be delivered."""


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str, *, timeout: float = 5.0,
                 session: requests.Session | None = None) -> None:
        if not token.strip():
            raise ValueError("telegram token is required")
        if not chat_id.strip():
            raise ValueError("telegram chat id is required")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.token = token
        self.chat_id = chat_id
        self.timeout = timeout
        self.session = session or requests.Session()

    def __call__(self, message: str) -> None:
        if not message.strip():
            raise ValueError("message is required")
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            response = self.session.post(
                url,
                json={"chat_id": self.chat_id, "text": message},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise NotificationError(f"Telegram request failed: {exc}") from exc
        if not response.ok:
            raise NotificationError(f"Telegram request failed ({response.status_code})")
        try:
            body: Any = response.json()
        except ValueError as exc:
            raise NotificationError("Telegram response was not JSON") from exc
        if not isinstance(body, dict) or body.get("ok") is not True:
            raise NotificationError("Telegram rejected the notification")
