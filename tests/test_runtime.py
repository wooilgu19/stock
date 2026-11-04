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
        "last_tick_at": None,
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


class BacklogWorker:
    """Queue stand-in holding ``pending`` ticks; each call returns up to ``count``."""

    def __init__(self, pending, clock=None, step=0.0):
        self.pending = pending
        self.calls = []
        self.clock = clock
        self.step = step

    def process_once(self, count=10):
        self.calls.append(count)
        if self.clock is not None:
            self.clock[0] += self.step
        taken = min(count, self.pending)
        self.pending -= taken
        from datetime import datetime, timezone
        from src.models import Signal, SignalAction
        ts = datetime(2026, 11, 4, tzinfo=timezone.utc)
        return [Signal("005930", SignalAction.HOLD, 0.0, 100.0, "t", ts)] * taken


def test_run_once_drains_backlog_in_one_cycle():
    """Regression (2026-10-29, 11-02): reading one 10-tick batch per 1s poll
    left the paper loop 20-80 minutes behind the market on busy days."""
    worker = BacklogWorker(pending=1_005)
    runtime = TradingRuntime(worker, poll_interval=1.0)

    cycle = runtime.run_once(count=10)

    assert len(cycle.signals) == 1_005
    assert worker.pending == 0
    assert cycle.backlog is False


def test_run_once_stops_draining_after_time_budget(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("src.runtime.monotonic", lambda: clock[0])
    worker = BacklogWorker(pending=1_000, clock=clock, step=0.4)
    runtime = TradingRuntime(worker, poll_interval=1.0, max_drain_seconds=1.0)

    cycle = runtime.run_once(count=10)

    assert len(worker.calls) == 3  # 0.4, 0.8, 1.2s -> budget exhausted
    assert cycle.backlog is True
    assert worker.pending == 970


def test_run_skips_poll_sleep_while_backlog_remains():
    class CountingEvent(Event):
        def __init__(self):
            super().__init__()
            self.waits = []

        def wait(self, timeout=None):
            self.waits.append(timeout)
            return False

    worker = BacklogWorker(pending=25)
    runtime = TradingRuntime(worker, poll_interval=1.0, max_drain_seconds=0)
    stop = CountingEvent()

    runtime.run(stop, count=10, max_cycles=4)

    # cycles 1-2 read full batches (backlog, no sleep); cycle 3 reads 5 and
    # cycle 4 reads 0, so only those two sleep.
    assert worker.calls == [10, 10, 10, 10]
    assert len(stop.waits) == 2


def test_runtime_records_last_tick_time_in_metrics():
    metrics = RuntimeMetrics()
    TradingRuntime(BacklogWorker(pending=3), poll_interval=0, metrics=metrics).run_once(count=10)
    assert metrics.last_tick_at is not None


def test_runtime_rejects_negative_drain_budget():
    with pytest.raises(ValueError, match="max_drain_seconds"):
        TradingRuntime(FakeWorker(), max_drain_seconds=-1)
