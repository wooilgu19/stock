"""Redis Streams adapter, imported lazily so tests can run without Redis."""

import json
from typing import Any

from src.models import Tick


class RedisQueueError(RuntimeError):
    """Raised when Redis is unavailable or a stream entry is malformed."""


class RedisQueue:
    def __init__(self, host: str = "localhost", port: int = 6379, stream: str = "stock:ticks",
                 maxlen: int = 100_000) -> None:
        if not host.strip():
            raise ValueError("host is required")
        if not 1 <= port <= 65_535:
            raise ValueError("port must be between 1 and 65535")
        if not stream.strip():
            raise ValueError("stream is required")
        if maxlen <= 0:
            raise ValueError("maxlen must be positive")
        try:
            import redis
        except ImportError as exc:
            raise RuntimeError("redis package is required to use RedisQueue") from exc
        # redis-py negotiates RESP3 (a HELLO handshake) by default; Redis
        # servers older than 6.0 (and some managed/compatible services)
        # don't implement HELLO and reject the connection outright. RESP2
        # is all this adapter needs, so pin it for broad compatibility.
        self.client = redis.Redis(host=host, port=port, decode_responses=True,
                                  socket_connect_timeout=2.0, socket_timeout=2.0,
                                  protocol=2)
        self.stream = stream
        self.maxlen = maxlen
        self._redis_error = redis.exceptions.RedisError

    def publish(self, message: dict[str, Any]) -> str:
        if not isinstance(message, dict):
            raise TypeError("message must be a dictionary")
        try:
            return str(self.client.xadd(self.stream, {"payload": json.dumps(message)}, maxlen=self.maxlen, approximate=True))
        except self._redis_error as exc:
            raise RedisQueueError("Redis publish failed") from exc

    def ping(self) -> None:
        """Raise when Redis is unavailable."""
        try:
            self.client.ping()
        except self._redis_error as exc:
            raise RedisQueueError("Redis ping failed") from exc

    def publish_tick(self, tick: Tick) -> str:
        return self.publish({
            "symbol": tick.symbol,
            "price": tick.price,
            "volume": tick.volume,
            "timestamp": tick.timestamp.isoformat(),
        })

    def read(self, last_id: str = "0-0", count: int = 10) -> list[tuple[str, dict[str, Any]]]:
        if not last_id.strip():
            raise ValueError("last_id is required")
        if count <= 0:
            raise ValueError("count must be positive")
        try:
            entries = self.client.xread({self.stream: last_id}, count=count, block=1000)
        except self._redis_error as exc:
            raise RedisQueueError("Redis read failed") from exc
        return [
            (entry_id, self._decode_payload(fields))
            for _, records in entries for entry_id, fields in records
        ]

    @staticmethod
    def _decode_payload(fields: dict[str, Any]) -> dict[str, Any]:
        payload = fields.get("payload")
        if not isinstance(payload, str):
            raise RedisQueueError("Redis stream entry has no payload")
        try:
            message = json.loads(payload)
        except (TypeError, ValueError) as exc:
            raise RedisQueueError("Redis stream payload is not valid JSON") from exc
        if not isinstance(message, dict):
            raise RedisQueueError("Redis stream payload is not an object")
        return message
