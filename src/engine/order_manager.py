"""Order orchestration with a paper-trading default."""

from dataclasses import dataclass

from src.database.sqlite import TradeRepository
from src.engine.risk import RiskGate
from src.models import OrderRequest, TradeLog


@dataclass(frozen=True)
class OrderResult:
    accepted: bool
    order_id: str | None = None
    reason: str = ""


class OrderManager:
    def __init__(self, repository: TradeRepository, risk_gate: RiskGate, paper_trading: bool = True) -> None:
        self.repository = repository
        self.risk_gate = risk_gate
        self.paper_trading = paper_trading

    def submit(self, order: OrderRequest) -> OrderResult:
        decision = self.risk_gate.check(order, self.repository.daily_realized_loss())
        if not decision.allowed:
            return OrderResult(False, reason=decision.reason)

        order_id = f"paper-{order.timestamp.timestamp()}" if self.paper_trading else None
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
        return OrderResult(True, order_id or f"trade-{trade_id}")
