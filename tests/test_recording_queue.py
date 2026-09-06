import json

from src.queue.recording_queue import RecordingQueue


class FakeQueue:
    def __init__(self):
        self.published = []

    def publish(self, message):
        self.published.append(message)
        return "1-0"


def test_publish_forwards_to_inner_queue_and_returns_its_id(tmp_path):
    inner = FakeQueue()
    recorder = RecordingQueue(inner, tmp_path / "ticks.jsonl")

    result = recorder.publish({"symbol": "005930", "price": 70000})

    assert result == "1-0"
    assert inner.published == [{"symbol": "005930", "price": 70000}]


def test_delegates_unknown_attributes_to_inner_queue(tmp_path):
    class QueueWithRead:
        def publish(self, message):
            return "1-0"

        def read(self, last_id="0-0", count=10):
            return [("1-0", {"symbol": "005930"})]

    recorder = RecordingQueue(QueueWithRead(), tmp_path / "ticks.jsonl")

    assert recorder.read() == [("1-0", {"symbol": "005930"})]


def test_publish_appends_one_jsonl_line_per_call(tmp_path):
    inner = FakeQueue()
    path = tmp_path / "ticks.jsonl"
    recorder = RecordingQueue(inner, path)

    recorder.publish({"symbol": "005930", "price": 70000})
    recorder.publish({"symbol": "005930", "price": 70100})

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["payload"] == {"symbol": "005930", "price": 70000}
    assert isinstance(first["ts"], (int, float))


def test_publish_still_succeeds_when_file_write_fails(tmp_path, monkeypatch):
    inner = FakeQueue()
    recorder = RecordingQueue(inner, tmp_path / "ticks.jsonl")

    def broken_open(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("builtins.open", broken_open)

    result = recorder.publish({"symbol": "005930", "price": 70000})

    assert result == "1-0"
    assert inner.published == [{"symbol": "005930", "price": 70000}]
