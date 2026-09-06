"""Replays a JSONL tick recording (from RecordingQueue) back onto a queue.

Stands in for the live KIS websocket collector in src.main when running
with --replay, so the trading loop can be observed outside market hours
using previously recorded real ticks.
"""

import asyncio
import json
import threading
from pathlib import Path
from typing import Any


async def replay_ticks(path: str | Path, queue: Any, stop_event: threading.Event) -> None:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ValueError(f"replay file is empty: {path}")

    rows = []
    for line in lines:
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid replay line in {path}: {line!r}") from exc

    previous_ts = rows[0]["ts"]
    for row in rows:
        gap = row["ts"] - previous_ts
        if gap > 0:
            await asyncio.sleep(gap)
        if stop_event.is_set():
            return
        previous_ts = row["ts"]
        queue.publish(row["payload"])
