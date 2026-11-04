"""Runtime loop for the assembled trading pipeline."""

import logging
from dataclasses import dataclass
from collections.abc import Callable
from threading import Event
from time import monotonic

from src.engine.reconciliation import OrderReconciler, ReconciliationResult
from src.inference.worker import InferenceWorker
from src.monitoring.metrics import RuntimeMetrics
from src.models import Signal


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RuntimeCycle:
    signals: list[Signal]
    reconciliation: ReconciliationResult | None = None
    errors: tuple[str, ...] = ()
    # True when the last read returned a full batch, i.e. more ticks are
    # probably already waiting; run() then skips its poll sleep.
    backlog: bool = False


class TradingRuntime:
    """Run inference and optional order reconciliation in controlled cycles."""

    def __init__(self, worker: InferenceWorker,
                 reconciler: OrderReconciler | None = None,
                 poll_interval: float = 1.0,
                 metrics: RuntimeMetrics | None = None,
                 on_error: Callable[[str], None] | None = None,
                 reconcile_every: int = 1,
                 max_drain_seconds: float = 1.0) -> None:
        if poll_interval < 0:
            raise ValueError("poll_interval cannot be negative")
        if reconcile_every <= 0:
            raise ValueError("reconcile_every must be positive")
        if max_drain_seconds < 0:
            raise ValueError("max_drain_seconds cannot be negative")
        self.worker = worker
        self.reconciler = reconciler
        self.poll_interval = poll_interval
        self.metrics = metrics
        self.on_error = on_error
        # Reconciliation pages through KIS's order-status REST endpoint on
        # the same thread as tick processing; running it every cycle lets a
        # busy order book's pagination (and rate-limit backoff) starve tick
        # processing. Running it every Nth cycle instead bounds that cost
        # without adding a second thread.
        self.reconcile_every = reconcile_every
        self._cycles_since_reconcile = 0
        # Upper bound on how long one cycle keeps draining a tick backlog
        # before yielding to reconciliation and the stop check.  Reading a
        # fixed small batch per poll (10 ticks/s) used to fall 20-80 minutes
        # behind the market on busy days (2026-10-29, 11-02).
        self.max_drain_seconds = max_drain_seconds

    def run_once(self, count: int = 10) -> RuntimeCycle:
        if count <= 0:
            raise ValueError("count must be positive")
        errors: list[str] = []
        signals: list[Signal] = []
        backlog = False
        started = monotonic()
        try:
            while True:
                batch = self.worker.process_once(count)
                signals.extend(batch)
                backlog = len(batch) >= count
                if not backlog or monotonic() - started >= self.max_drain_seconds:
                    break
        except Exception as exc:
            backlog = False
            errors.append(self._format_error("worker", exc))

        reconciliation = None
        self._cycles_since_reconcile += 1
        if self.reconciler and self._cycles_since_reconcile >= self.reconcile_every:
            self._cycles_since_reconcile = 0
            try:
                reconciliation = self.reconciler.reconcile()
            except Exception as exc:
                errors.append(self._format_error("reconciliation", exc))
        cycle = RuntimeCycle(signals, reconciliation, tuple(errors), backlog)
        if self.metrics:
            self.metrics.record(len(cycle.signals), cycle.errors, cycle.reconciliation,
                                last_tick_at=signals[-1].timestamp if signals else None)
        for error in cycle.errors:
            logger.error("trading runtime error: %s", error)
            if self.on_error:
                try:
                    self.on_error(error)
                except Exception:
                    logger.exception("runtime error handler failed")
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
        if count <= 0:
            raise ValueError("count must be positive")
        cycles = 0
        while not stop_event.is_set() and (max_cycles is None or cycles < max_cycles):
            started = monotonic()
            cycle = self.run_once(count)
            cycles += 1
            if cycle.backlog:
                continue
            remaining = self.poll_interval - (monotonic() - started)
            if remaining > 0:
                stop_event.wait(remaining)
        return cycles
