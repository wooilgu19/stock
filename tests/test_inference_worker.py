from src.inference.worker import InferenceWorker, tick_from_message
from src.models import SignalAction
from src.strategies.moving_average import MovingAverageStrategy


class FakeQueue:
    def __init__(self, entries):
        self.entries = entries
        self.calls = []

    def read(self, last_id, count):
        self.calls.append((last_id, count))
        entries, self.entries = self.entries, []
        return entries


def message(message_id, price):
    return message_id, {"symbol": "005930", "price": price, "volume": 10,
                        "timestamp": "2026-01-01T00:00:00+00:00"}


def test_worker_advances_stream_cursor_and_emits_signals():
    queue = FakeQueue([message("1-0", 100), message("2-0", 101)])
    emitted = []
    worker = InferenceWorker(queue, MovingAverageStrategy(2, 3), emitted.append)

    signals = worker.process_once()

    assert len(signals) == 2
    assert worker.last_id == "2-0"
    assert emitted == signals
    assert queue.calls == [("0-0", 10)]


def test_strategy_holds_until_long_window_is_ready():
    strategy = MovingAverageStrategy(2, 3)
    signal = strategy.on_tick(tick_from_message(message("1-0", 100)[1]))
    assert signal.action == SignalAction.HOLD
