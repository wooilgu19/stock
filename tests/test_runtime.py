from threading import Event

import pytest

from src.runtime import TradingRuntime
from src.monitoring.metrics import RuntimeMetrics


class FakeWorker:
    def __init__(self):
        self.calls = []

    def process_once(self, count=10):
        self.calls.append(count)
        return []


class FakeReconciler:
    def __init__(self):
        self.calls = 0

    def reconcile(self):
        self.calls += 1
        return "reconciled"


class FailingWorker(FakeWorker):
    def process_once(self, count=10):
        self.calls.append(count)
        raise RuntimeError("queue unavailable")


class FailingReconciler(FakeReconciler):
    def reconcile(self):
        self.calls += 1
        raise RuntimeError("broker unavailable")


def test_runtime_runs_one_cycle_with_reconciliation():
    worker = FakeWorker()
    reconciler = FakeReconciler()
    runtime = TradingRuntime(worker, reconciler, poll_interval=0)

    cycle = runtime.run_once(count=3)

    assert cycle.signals == []
    assert cycle.reconciliation == "reconciled"
    assert worker.calls == [3]
    assert reconciler.calls == 1


def test_runtime_stops_after_requested_cycles():
    worker = FakeWorker()
    runtime = TradingRuntime(worker, poll_interval=0)

    cycles = runtime.run(Event(), count=2, max_cycles=2)

    assert cycles == 2
    assert worker.calls == [2, 2]


def test_runtime_reports_worker_and_reconciliation_errors_without_stopping():
    cycle = TradingRuntime(
        FailingWorker(), FailingReconciler(), poll_interval=0,
    ).run_once()

    assert cycle.signals == []
    assert cycle.reconciliation is None
    assert cycle.errors == ("worker: queue unavailable", "reconciliation: broker unavailable")


def test_runtime_continues_after_cycle_error():
    runtime = TradingRuntime(FailingWorker(), poll_interval=0)

    assert runtime.run(Event(), max_cycles=2) == 2


def test_runtime_records_metrics():
    metrics = RuntimeMetrics()
    runtime = TradingRuntime(FakeWorker(), FakeReconciler(), poll_interval=0, metrics=metrics)

    runtime.run_once()

    assert metrics.as_dict() == {
        "cycles": 1,
        "signals": 0,
        "errors": 0,
        "reconciliation_updates": 0,
        "reconciliation_ignored": 0,
        "last_error": None,
    }


def test_runtime_notifies_error_handler_without_stopping():
    errors = []
    runtime = TradingRuntime(
        FailingWorker(), poll_interval=0, on_error=errors.append,
    )

    cycle = runtime.run_once()

    assert cycle.errors == ("worker: queue unavailable",)
    assert errors == ["worker: queue unavailable"]


def test_runtime_ignores_error_handler_failure():
    def failing_handler(error):
        raise RuntimeError("notification unavailable")

    cycle = TradingRuntime(
        FailingWorker(), poll_interval=0, on_error=failing_handler,
    ).run_once()

    assert cycle.errors == ("worker: queue unavailable",)


def test_runtime_rejects_invalid_options():
    with pytest.raises(ValueError):
        TradingRuntime(FakeWorker(), poll_interval=-1)
    with pytest.raises(ValueError):
        TradingRuntime(FakeWorker()).run(Event(), max_cycles=0)
    with pytest.raises(ValueError, match="count"):
        TradingRuntime(FakeWorker()).run_once(count=0)
    with pytest.raises(ValueError, match="count"):
        TradingRuntime(FakeWorker()).run(Event(), count=0)
