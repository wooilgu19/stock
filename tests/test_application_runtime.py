from src.application import build_runtime
from src.config import Settings
from src.database.sqlite import TradeRepository
from src.engine.reconciliation import OrderReconciler
from src.monitoring.metrics import RuntimeMetrics
from src.monitoring.notifications import TelegramNotifier


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


def test_build_runtime_injects_reconciler(tmp_path):
    repository = TradeRepository(tmp_path / "reconcile.sqlite3")
    reconciler = OrderReconciler(repository, lambda: [])
    runtime = build_runtime(
        Settings(database_path=tmp_path / "trades.sqlite3"),
        UnusedPredictor(), EmptyQueue(), reconciler=reconciler,
    )

    cycle = runtime.run_once()

    assert cycle.reconciliation is not None
    assert cycle.reconciliation.updated == 0


def test_build_runtime_injects_metrics(tmp_path):
    metrics = RuntimeMetrics()
    runtime = build_runtime(
        Settings(database_path=tmp_path / "trades.sqlite3"),
        UnusedPredictor(), EmptyQueue(), poll_interval=0, metrics=metrics,
    )

    runtime.run_once()

    assert metrics.cycles == 1


def test_build_runtime_enables_telegram_notifier_without_network_call(tmp_path):
    runtime = build_runtime(
        Settings(
            database_path=tmp_path / "trades.sqlite3",
            telegram_token="token",
            telegram_chat_id="chat",
        ),
        UnusedPredictor(), EmptyQueue(), poll_interval=0,
    )

    assert isinstance(runtime.on_error, TelegramNotifier)
