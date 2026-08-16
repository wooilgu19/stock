from src.application import build_runtime
from src.config import Settings


class EmptyQueue:
    def read(self, last_id="0-0", count=10):
        return []


class UnusedPredictor:
    def on_tick(self, tick):
        raise AssertionError("no tick should be processed")


def test_build_runtime_is_not_started_during_construction(tmp_path):
    runtime = build_runtime(
        Settings(database_path=tmp_path / "trades.sqlite3"),
        UnusedPredictor(),
        queue=EmptyQueue(),
        poll_interval=0,
    )

    assert runtime.poll_interval == 0
    assert runtime.worker.last_id == "0-0"
