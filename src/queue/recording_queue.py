"""Wraps a tick queue to also append every published message to a JSONL file.

Used during live weekday runs (via ``src.main --record``) so the exact tick
stream can be replayed later outside market hours through
``src.replay.replay_ticks``.
"""

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class RecordingQueue:
    def __init__(self, inner: Any, path: str | Path) -> None:
        self.inner = inner
        self.path = Path(path)

    def publish(self, message: dict[str, Any]) -> str:
        result = self.inner.publish(message)
        try:
            line = json.dumps({"ts": time.time(), "payload": message})
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except (OSError, TypeError, ValueError):
            logger.warning("failed to record tick to %s", self.path, exc_info=True)
        return result

    def __getattr__(self, name: str) -> Any:
        # Only publish() is intercepted (to also append to the recording
        # file); every other attribute/method (read, ping, stream, ...)
        # passes straight through to the wrapped queue untouched, so this
        # stays a drop-in wrapper for callers that need more than publish().
        return getattr(self.inner, name)
