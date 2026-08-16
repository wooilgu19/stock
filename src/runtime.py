"""Runtime loop for the assembled trading pipeline."""

from dataclasses import dataclass
from threading import Event
from time import monotonic

from src.engine.reconciliation import OrderReconciler, ReconciliationResult
from src.inference.worker import InferenceWorker
from src.monitoring.metrics import RuntimeMetrics
from src.models import Signal


@dataclass(frozen=True)
class RuntimeCycle:
    signals: list[Signal]
    reconciliation: ReconciliationResult | None = None
    errors: tuple[str, ...] = ()


class TradingRuntime:
    """Run inference and optional order reconciliation in controlled cycles."""

    def __init__(self, worker: InferenceWorker,
                 reconciler: OrderReconciler | None = None,
                 poll_interval: float = 1.0,
                 metrics: RuntimeMetrics | None = None) -> None:
        if poll_interval < 0:
            raise ValueError("poll_interval cannot be negative")
        self.worker = worker
        self.reconciler = reconciler
        self.poll_interval = poll_interval
        self.metrics = metrics

    def run_once(self, count: int = 10) -> RuntimeCycle:
        errors: list[str] = []
        try:
            signals = self.worker.process_once(count)
        except Exception as exc:
            signals = []
            errors.append(self._format_error("worker", exc))

        reconciliation = None
        if self.reconciler:
            try:
                reconciliation = self.reconciler.reconcile()
            except Exception as exc:
                errors.append(self._format_error("reconciliation", exc))
        cycle = RuntimeCycle(signals, reconciliation, tuple(errors))
        if self.metrics:
            self.metrics.record(len(cycle.signals), cycle.errors, cycle.reconciliation)
        return cycle

    @staticmethod
    def _format_error(component: str, error: Exception) -> str:
        message = str(error).strip() or error.__class__.__name__
        return f"{component}: {message}"

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
