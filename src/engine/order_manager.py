"""Order orchestration with a paper-trading default."""

from dataclasses import dataclass
from typing import Protocol

from src.database.sqlite import TradeRepository
from src.engine.market_hours import MarketHours
from src.engine.portfolio import PortfolioState
from src.engine.risk import RiskGate
from src.models import OrderRequest, TradeLog


@dataclass(frozen=True)
class OrderResult:
    accepted: bool
    order_id: str | None = None
    reason: str = ""


class OrderExecutor(Protocol):
    """Broker boundary used for non-paper orders.

    Implementations must return the broker-assigned order id only after the
    broker has accepted the order.  Keeping this boundary explicit prevents a
    live configuration from silently becoming a database-only simulation.
    """

    def submit(self, order: OrderRequest) -> str: ...


class OrderManager:
    def __init__(self, repository: TradeRepository, risk_gate: RiskGate,
                 paper_trading: bool = True, market_hours: MarketHours | None = None,
                 portfolio: PortfolioState | None = None,
                 executor: OrderExecutor | None = None) -> None:
        self.repository = repository
        self.risk_gate = risk_gate
        self.paper_trading = paper_trading
        self.market_hours = market_hours
        self.portfolio = portfolio
        self.executor = executor

    def submit(self, order: OrderRequest) -> OrderResult:
        if order.client_order_id and self.repository.has_order_id(order.client_order_id):
            return OrderResult(True, order.client_order_id, "duplicate order already recorded")
        if self.market_hours and not self.market_hours.is_open(order.timestamp):
            return OrderResult(False, reason="market is closed")
        decision = self.risk_gate.check(order, self.repository.daily_realized_loss())
        if not decision.allowed:
            return OrderResult(False, reason=decision.reason)
        if self.portfolio:
            portfolio_reason = self.portfolio.check(order)
            if portfolio_reason:
                return OrderResult(False, reason=portfolio_reason)

        if not self.paper_trading and self.executor is None:
            return OrderResult(False, reason="live order executor is not configured")

        if self.paper_trading:
            order_id = order.client_order_id or f"paper-{order.timestamp.timestamp()}"
        else:
            # The guard above makes the executor non-optional on this path.
            order_id = self.executor.submit(order)  # type: ignore[union-attr]
        trade_id = self.repository.save(TradeLog(
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=order.price,
            strategy_id=order.strategy_id,
            signal_strength=order.signal_strength,
            status="simulated" if self.paper_trading else "submitted",
            timestamp=order.timestamp,
            broker_order_id=order_id,
        ))
        if self.portfolio:
            self.portfolio.apply(order)
        return OrderResult(True, order_id or f"trade-{trade_id}")
