"""KIS domestic stock real-time execution-price WebSocket client."""

import json
from collections.abc import AsyncIterator, Iterable
from datetime import datetime, timezone
from typing import Any

import requests
import websockets

from src.models import Tick


REALTIME_PRICE_TR_ID = "H0STCNT0"
REAL_WS_URL = "ws://ops.koreainvestment.com:21000"
PAPER_WS_URL = "ws://ops.koreainvestment.com:31000"


class KISWebSocketError(RuntimeError):
    """Raised for WebSocket authentication or protocol errors."""


class KISWebSocketClient:
    def __init__(self, app_key: str, app_secret: str, *, paper_trading: bool = True,
                 base_url: str = "https://openapi.koreainvestment.com:9443",
                 ws_url: str | None = None, timeout: float = 10.0,
                 http_session: requests.Session | None = None) -> None:
        self.app_key = app_key
        self.app_secret = app_secret
        self.base_url = base_url.rstrip("/")
        self.ws_url = ws_url or (PAPER_WS_URL if paper_trading else REAL_WS_URL)
        self.timeout = timeout
        self.http_session = http_session or requests.Session()

    def approval_key(self) -> str:
        response = self.http_session.post(
            self.base_url + "/oauth2/Approval",
            headers={"content-type": "application/json"},
            json={"grant_type": "client_credentials", "appkey": self.app_key,
                  "secretkey": self.app_secret},
            timeout=self.timeout,
        )
        if not response.ok:
            raise KISWebSocketError(f"approval request failed ({response.status_code})")
        try:
            body = response.json()
            return body["approval_key"]
        except (ValueError, KeyError) as exc:
            raise KISWebSocketError("approval response did not contain approval_key") from exc

    @staticmethod
    def subscription_message(approval_key: str, symbol: str, *, subscribe: bool = True) -> str:
        if not symbol.strip():
            raise ValueError("symbol is required")
        return json.dumps({
            "header": {
                "approval_key": approval_key,
                "custtype": "P",
                "tr_type": "1" if subscribe else "2",
                "content-type": "utf-8",
            },
            "body": {"input": {"tr_id": REALTIME_PRICE_TR_ID, "tr_key": symbol}},
        })

    @staticmethod
    def parse_message(message: str | bytes) -> Tick | None:
        """Parse an unencrypted H0STCNT0 message into a Tick.

        Encrypted payloads are intentionally rejected until the account's
        AES key exchange is implemented; silently parsing them would create
        invalid trading data.
        """
        if isinstance(message, bytes):
            message = message.decode("utf-8")
        if message.startswith("{"):
            return None
        parts = message.split("|", 3)
        if len(parts) != 4 or parts[0] != "0" or parts[1] != REALTIME_PRICE_TR_ID:
            return None
        fields = parts[3].split("|")
        if len(fields) < 13:
            raise KISWebSocketError("H0STCNT0 payload has too few fields")
        try:
            return Tick(
                symbol=fields[0],
                price=float(fields[2]),
                volume=int(fields[12]),
                timestamp=datetime.now(timezone.utc),
            )
        except (ValueError, IndexError) as exc:
            raise KISWebSocketError("invalid H0STCNT0 payload") from exc

    async def stream(self, symbols: Iterable[str]) -> AsyncIterator[Tick]:
        symbols = tuple(symbol.strip() for symbol in symbols if symbol.strip())
        if not symbols:
            raise ValueError("at least one symbol is required")
        approval_key = self.approval_key()
        async with websockets.connect(self.ws_url, open_timeout=self.timeout) as socket:
            for symbol in symbols:
                await socket.send(self.subscription_message(approval_key, symbol))
            async for message in socket:
                tick = self.parse_message(message)
                if tick is not None:
                    yield tick

    async def stream_to_queue(self, symbols: Iterable[str], queue: Any) -> None:
        """Forward parsed ticks to an object exposing ``publish(dict)``."""
        async for tick in self.stream(symbols):
            queue.publish({
                "symbol": tick.symbol,
                "price": tick.price,
                "volume": tick.volume,
                "timestamp": tick.timestamp.isoformat(),
            })
