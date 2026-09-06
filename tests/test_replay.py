import asyncio
import json
import threading

import pytest

from src.replay import replay_ticks


class FakeQueue:
    def __init__(self):
        self.published = []

    def publish(self, message):
        self.published.append(message)
        return "1-0"


def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def test_replay_publishes_each_payload_in_order(tmp_path):
    path = tmp_path / "ticks.jsonl"
    write_jsonl(path, [
        {"ts": 100.0, "payload": {"symbol": "005930", "price": 70000}},
        {"ts": 100.0, "payload": {"symbol": "005930", "price": 70100}},
    ])
    queue = FakeQueue()

    asyncio.run(replay_ticks(path, queue, threading.Event()))

    assert queue.published == [
        {"symbol": "005930", "price": 70000},
        {"symbol": "005930", "price": 70100},
    ]


def test_replay_sleeps_for_the_recorded_gap_between_ticks(tmp_path, monkeypatch):
    path = tmp_path / "ticks.jsonl"
    write_jsonl(path, [
        {"ts": 100.0, "payload": {"symbol": "005930", "price": 70000}},
        {"ts": 102.5, "payload": {"symbol": "005930", "price": 70100}},
    ])
    queue = FakeQueue()
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr("src.replay.asyncio.sleep", fake_sleep)

    asyncio.run(replay_ticks(path, queue, threading.Event()))

    assert sleeps == [2.5]


def test_replay_stops_promptly_when_stop_event_is_set(tmp_path, monkeypatch):
    path = tmp_path / "ticks.jsonl"
    write_jsonl(path, [
        {"ts": 100.0, "payload": {"symbol": "005930", "price": 70000}},
        {"ts": 200.0, "payload": {"symbol": "005930", "price": 70100}},
        {"ts": 300.0, "payload": {"symbol": "005930", "price": 70200}},
    ])
    queue = FakeQueue()
    stop_event = threading.Event()

    async def fake_sleep(seconds):
        stop_event.set()

    monkeypatch.setattr("src.replay.asyncio.sleep", fake_sleep)

    asyncio.run(replay_ticks(path, queue, stop_event))

    assert queue.published == [{"symbol": "005930", "price": 70000}]


def test_replay_raises_on_empty_file(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="empty"):
        asyncio.run(replay_ticks(path, FakeQueue(), threading.Event()))


def test_replay_raises_on_malformed_first_line(tmp_path):
    path = tmp_path / "broken.jsonl"
    path.write_text("not json\n", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid"):
        asyncio.run(replay_ticks(path, FakeQueue(), threading.Event()))
