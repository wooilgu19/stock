"""KIS domestic stock real-time execution-price WebSocket client."""

import json
import asyncio
import logging
from collections.abc import AsyncIterator, Iterable
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import requests
import websockets

from src.models import Tick

logger = logging.getLogger(__name__)


REALTIME_PRICE_TR_ID = "H0STCNT0"
REAL_WS_URL = "ws://ops.koreainvestment.com:21000"
PAPER_WS_URL = "ws://ops.koreainvestment.com:31000"
# H0STCNT0 packs this many pipe-delimited fields per execution record; a
# multi-record frame (count > 1) concatenates that many of them back to back.
_RECORD_FIELD_COUNT = 46
# KIS's live gateway drops trailing empty optional fields instead of sending
# them as empty pipe segments, so a real record can be shorter than the
# documented 46 -- but never shorter than the fields this client actually
# reads (symbol, exec time, price, volume -- highest index 12).
_RECORD_FIELDS_REQUIRED = 13
_KST = ZoneInfo("Asia/Seoul")


class KISWebSocketError(RuntimeError):
    """Raised for WebSocket authentication or protocol errors."""


class _StreamClosedNormally(Exception):
    """Internal signal that the socket ended its message iteration cleanly.

    KIS closes idle/daily sessions without a close frame the websockets
    library treats as abnormal, so `async for message in socket` simply
    exhausts. That must trigger the same reconnect path as a dropped
    connection instead of ending the generator silently.
    """


class KISWebSocketClient:
    def __init__(self, app_key: str, app_secret: str, *, paper_trading: bool = True,
                 base_url: str = "https://openapi.koreainvestment.com:9443",
                 ws_url: str | None = None, timeout: float = 10.0,
                 http_session: requests.Session | None = None,
                 max_reconnects: int = 3, reconnect_delay: float = 1.0) -> None:
        if max_reconnects < 0:
            raise ValueError("max_reconnects cannot be negative")
        if reconnect_delay < 0:
            raise ValueError("reconnect_delay cannot be negative")
        self.app_key = app_key
        self.app_secret = app_secret
        self.base_url = base_url.rstrip("/")
        self.ws_url = ws_url or (PAPER_WS_URL if paper_trading else REAL_WS_URL)
        self.timeout = timeout
        self.http_session = http_session or requests.Session()
        self.max_reconnects = max_reconnects
        self.reconnect_delay = reconnect_delay

    def approval_key(self) -> str:
        try:
            response = self.http_session.post(
                self.base_url + "/oauth2/Approval",
                headers={"content-type": "application/json"},
                json={"grant_type": "client_credentials", "appkey": self.app_key,
                      "secretkey": self.app_secret},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise KISWebSocketError(f"approval request failed: {exc}") from exc
        if not response.ok:
            raise KISWebSocketError(f"approval request failed ({response.status_code})")
        try:
            body = response.json()
        except ValueError as exc:
            raise KISWebSocketError("approval response did not contain approval_key") from exc
        if not isinstance(body, dict):
            raise KISWebSocketError("approval response was not an object")
        approval_key = body.get("approval_key")
        if not isinstance(approval_key, str) or not approval_key.strip():
            raise KISWebSocketError("approval response did not contain approval_key")
        return approval_key

    @staticmethod
    def subscription_message(approval_key: str, symbol: str, *, subscribe: bool = True) -> str:
        if not approval_key.strip():
            raise ValueError("approval_key is required")
        if not symbol.isdigit() or len(symbol) != 6:
            raise ValueError("domestic stock symbol must be a 6-digit code")
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
    def parse_ticks(message: str | bytes) -> list[Tick]:
        """Parse an unencrypted H0STCNT0 message into a Tick.

        Encrypted payloads are intentionally rejected until the account's
        AES key exchange is implemented; silently parsing them would create
        invalid trading data.
        """
        if isinstance(message, bytes):
            message = message.decode("utf-8")
        if message.startswith("{"):
            return []
        parts = message.split("|", 3)
        if len(parts) != 4 or parts[0] != "0" or parts[1] != REALTIME_PRICE_TR_ID:
            return []
        fields = parts[3].split("|")
        try:
            count = int(parts[2])
        except ValueError as exc:
            raise KISWebSocketError("invalid H0STCNT0 record count") from exc
        # Only the last record in a frame can be short (KIS trims trailing
        # empty fields off the wire, never mid-frame), so every record but
        # the last must still be full-width; the last only needs the fields
        # this client reads.
        min_len = (count - 1) * _RECORD_FIELD_COUNT + _RECORD_FIELDS_REQUIRED
        if count <= 0 or len(fields) < min_len:
            raise KISWebSocketError("H0STCNT0 payload has too few fields")
        ticks = []
        for offset in range(0, count * _RECORD_FIELD_COUNT, _RECORD_FIELD_COUNT):
            group = fields[offset:offset + _RECORD_FIELD_COUNT]
            try:
                ticks.append(Tick(symbol=group[0], price=float(group[2]),
                                  volume=int(group[12]),
                                  timestamp=KISWebSocketClient._execution_timestamp(group[1])))
            except (ValueError, IndexError) as exc:
                raise KISWebSocketError("invalid H0STCNT0 payload") from exc
        return ticks

    @staticmethod
    def _execution_timestamp(hhmmss: str) -> datetime:
        """Convert the exchange's KST execution time (HHMMSS) to UTC.

        The frame carries no date, so today's KST date is assumed. Using the
        exchange timestamp (rather than local receive time) keeps live
        feature timing consistent with timestamps recorded during training,
        which is not guaranteed under queueing delay or reconnect bursts.
        """
        if len(hhmmss) != 6 or not hhmmss.isdigit():
            raise ValueError("invalid H0STCNT0 execution time")
        hour, minute, second = int(hhmmss[0:2]), int(hhmmss[2:4]), int(hhmmss[4:6])
        now_kst = datetime.now(_KST)
        return now_kst.replace(
            hour=hour, minute=minute, second=second, microsecond=0
        ).astimezone(timezone.utc)

    @staticmethod
    def parse_message(message: str | bytes) -> Tick | None:
        ticks = KISWebSocketClient.parse_ticks(message)
        return ticks[0] if ticks else None

    async def stream(self, symbols: Iterable[str]) -> AsyncIterator[Tick]:
        symbols = tuple(symbol.strip() for symbol in symbols if symbol.strip())
        if not symbols:
            raise ValueError("at least one symbol is required")
        reconnects = 0
        while True:
            try:
                approval_key = self.approval_key()
                async with websockets.connect(self.ws_url, open_timeout=self.timeout) as socket:
                    reconnects = 0
                    for symbol in symbols:
                        await socket.send(self.subscription_message(approval_key, symbol))
                    async for message in socket:
                        try:
                            ticks = self.parse_ticks(message)
                        except KISWebSocketError:
                            # One malformed frame must not take down a
                            # multi-hour session; log it for post-mortem and
                            # keep reading -- the next frame is independent.
                            logger.exception("dropping unparseable H0STCNT0 message: %r", message)
                            continue
                        for tick in ticks:
                            yield tick
                    raise _StreamClosedNormally()
            except (websockets.exceptions.ConnectionClosed, OSError,
                    asyncio.TimeoutError, _StreamClosedNormally) as exc:
                if reconnects >= self.max_reconnects:
                    raise KISWebSocketError("WebSocket reconnect limit exceeded") from exc
                await asyncio.sleep(self.reconnect_delay * (2 ** reconnects))
                reconnects += 1

    async def stream_to_queue(self, symbols: Iterable[str], queue: Any) -> None:
        """Forward parsed ticks to an object exposing ``publish(dict)``."""
        async for tick in self.stream(symbols):
            await asyncio.to_thread(queue.publish, {
                "symbol": tick.symbol,
                "price": tick.price,
                "volume": tick.volume,
                "timestamp": tick.timestamp.isoformat(),
            })
