"""Minimal in-memory portfolio state for paper-trading pre-checks."""

from dataclasses import dataclass, field

from src.models import OrderRequest, Side


@dataclass
class PortfolioState:
    cash: float
    positions: dict[str, int] = field(default_factory=dict)

    def check(self, order: OrderRequest) -> str | None:
        if order.side == Side.BUY and order.value > self.cash:
            return "insufficient cash"
        if order.side == Side.SELL and order.quantity > self.positions.get(order.symbol, 0):
            return "insufficient position"
        return None

    def apply(self, order: OrderRequest) -> None:
        reason = self.check(order)
        if reason:
            raise ValueError(reason)
        current = self.positions.get(order.symbol, 0)
        if order.side == Side.BUY:
            self.cash -= order.value
            self.positions[order.symbol] = current + order.quantity
        else:
            self.cash += order.value
            remaining = current - order.quantity
            if remaining:
                self.positions[order.symbol] = remaining
            else:
                self.positions.pop(order.symbol, None)
