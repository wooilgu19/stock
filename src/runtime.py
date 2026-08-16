"""Runtime loop for the assembled trading pipeline."""

from dataclasses import dataclass
from threading import Event
from time import monotonic

from src.engine.reconciliation import OrderReconciler, ReconciliationResult
from src.inference.worker import InferenceWorker
from src.models import Signal


@dataclass(frozen=True)
class RuntimeCycle:
    signals: list[Signal]
    reconciliation: ReconciliationResult | None = None


class TradingRuntime:
    """Run inference and optional order reconciliation in controlled cycles."""

    def __init__(self, worker: InferenceWorker,
                 reconciler: OrderReconciler | None = None,
                 poll_interval: float = 1.0) -> None:
        if poll_interval < 0:
            raise ValueError("poll_interval cannot be negative")
        self.worker = worker
        self.reconciler = reconciler
        self.poll_interval = poll_interval

    def run_once(self, count: int = 10) -> RuntimeCycle:
        signals = self.worker.process_once(count)
        reconciliation = self.reconciler.reconcile() if self.reconciler else None
        return RuntimeCycle(signals, reconciliation)

    def run(self, stop_event: Event, count: int = 10,
            max_cycles: int | None = None) -> int:
        """Run until stopped, returning the number of completed cycles."""
        if max_cycles is not None and max_cycles <= 0:
            raise ValueError("max_cycles must be positive")
        cycles = 0
        while not stop_event.is_set() and (max_cycles is None or cycles < max_cycles):
            started = monotonic()
            self.run_once(count)
            cycles += 1
            remaining = self.poll_interval - (monotonic() - started)
            if remaining > 0:
                stop_event.wait(remaining)
        return cycles
