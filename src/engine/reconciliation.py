"""Reconcile broker order lifecycle states with local trade logs."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from src.database.sqlite import TradeRepository
from src.models import OrderStatusUpdate


@dataclass(frozen=True)
class ReconciliationResult:
    updated: int
    ignored: int


class OrderReconciler:
    """Apply broker updates without allowing unknown orders into local state."""

    def __init__(self, repository: TradeRepository,
                 fetch_updates: Callable[[], Iterable[OrderStatusUpdate]]) -> None:
        self.repository = repository
        self.fetch_updates = fetch_updates

    def reconcile(self) -> ReconciliationResult:
        pending = self.repository.pending_order_ids()
        updated = 0
        ignored = 0
        for update in self.fetch_updates():
            if update.broker_order_id not in pending:
                ignored += 1
                continue
            if self.repository.update_order_status(update.broker_order_id, update.status):
                pending.remove(update.broker_order_id)
                updated += 1
            else:
                ignored += 1
        return ReconciliationResult(updated=updated, ignored=ignored)
