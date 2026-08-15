"""Minimal in-memory portfolio state for paper-trading pre-checks."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from src.models import OrderRequest, Side

if TYPE_CHECKING:
    from src.database.sqlite import TradeRepository


@dataclass
class PortfolioState:
    cash: float
    positions: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_repository(cls, repository: "TradeRepository", starting_cash: float) -> "PortfolioState":
        """Rebuild paper state from executions persisted before a restart."""
        if starting_cash < 0:
            raise ValueError("starting_cash cannot be negative")
        portfolio = cls(cash=starting_cash)
        for symbol, side, quantity, value in repository.executed_trade_totals():
            current = portfolio.positions.get(symbol, 0)
            if side == Side.BUY.value:
                portfolio.cash -= value
                portfolio.positions[symbol] = current + quantity
            elif side == Side.SELL.value:
                portfolio.cash += value
                remaining = current - quantity
                if remaining:
                    portfolio.positions[symbol] = remaining
                else:
                    portfolio.positions.pop(symbol, None)
        return portfolio

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
