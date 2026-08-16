from datetime import datetime, timezone

from src.application import build_pipeline
from src.config import Settings
from src.models import Signal, SignalAction


class FakeQueue:
    def __init__(self):
        self.entries = [("1-0", {
            "symbol": "005930", "price": 70000, "volume": 10,
            "timestamp": "2026-08-14T01:00:00+00:00",
        })]

    def read(self, last_id="0-0", count=10):
        entries, self.entries = self.entries, []
        return entries


class BuyPredictor:
    def on_tick(self, tick):
        return Signal(
            symbol=tick.symbol, action=SignalAction.BUY, strength=0.9,
            price=tick.price, strategy_id="test",
            timestamp=datetime(2026, 8, 14, 1, 0, tzinfo=timezone.utc),
        )


def test_build_pipeline_processes_tick_into_paper_order(tmp_path):
    settings = Settings(database_path=tmp_path / "trades.sqlite3")
    worker = build_pipeline(settings, BuyPredictor(), FakeQueue())

    signals = worker.process_once()

    assert len(signals) == 1
    with worker.on_signal.__self__.order_manager.repository._connect() as connection:
        row = connection.execute(
            "SELECT symbol, side, status FROM trade_logs"
        ).fetchone()
    assert tuple(row) == ("005930", "buy", "simulated")
