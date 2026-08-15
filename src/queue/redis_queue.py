"""Redis Streams adapter, imported lazily so tests can run without Redis."""

import json
from typing import Any


class RedisQueue:
    def __init__(self, host: str = "localhost", port: int = 6379, stream: str = "stock:ticks") -> None:
        try:
            import redis
        except ImportError as exc:
            raise RuntimeError("redis package is required to use RedisQueue") from exc
        self.client = redis.Redis(host=host, port=port, decode_responses=True)
        self.stream = stream

    def publish(self, message: dict[str, Any]) -> str:
        return str(self.client.xadd(self.stream, {"payload": json.dumps(message)}))

    def read(self, last_id: str = "0-0", count: int = 10) -> list[tuple[str, dict[str, Any]]]:
        entries = self.client.xread({self.stream: last_id}, count=count, block=1000)
        return [(entry_id, json.loads(fields["payload"]))
                for _, records in entries for entry_id, fields in records]
