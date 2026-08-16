"""In-memory counters for runtime observability."""

from dataclasses import dataclass
from typing import Any


@dataclass
class RuntimeMetrics:
    cycles: int = 0
    signals: int = 0
    errors: int = 0
    reconciliation_updates: int = 0
    reconciliation_ignored: int = 0
    last_error: str | None = None

    def record(self, signals: int, errors: tuple[str, ...] = (),
               reconciliation: Any = None) -> None:
        if signals < 0:
            raise ValueError("signals cannot be negative")
        self.cycles += 1
        self.signals += signals
        self.errors += len(errors)
        if errors:
            self.last_error = errors[-1]
        if reconciliation is not None:
            self.reconciliation_updates += int(getattr(reconciliation, "updated", 0))
            self.reconciliation_ignored += int(getattr(reconciliation, "ignored", 0))

    def as_dict(self) -> dict[str, Any]:
        return {
            "cycles": self.cycles,
            "signals": self.signals,
            "errors": self.errors,
            "reconciliation_updates": self.reconciliation_updates,
            "reconciliation_ignored": self.reconciliation_ignored,
            "last_error": self.last_error,
        }
