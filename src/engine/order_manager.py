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
                 executor: OrderExecutor | None = None,
                 max_consecutive_rejections: int = 3) -> None:
        if max_consecutive_rejections <= 0:
            raise ValueError("max_consecutive_rejections must be positive")
        self.repository = repository
        self.risk_gate = risk_gate
        self.paper_trading = paper_trading
        self.market_hours = market_hours
        self.portfolio = portfolio
        self.executor = executor
        self.max_consecutive_rejections = max_consecutive_rejections
        self._consecutive_rejections = 0
        self._halted_reason: str | None = None

    @property
    def halted(self) -> bool:
        """True once the kill switch has tripped; submit() rejects until reset."""
        return self._halted_reason is not None

    def reset_halt(self) -> None:
        """Manually clear the kill switch after the underlying issue is fixed."""
        self._halted_reason = None
        self._consecutive_rejections = 0

    def submit(self, order: OrderRequest) -> OrderResult:
        # Kill switch: this is the single path every live/paper order goes
        # through, so tripping it here blocks all further submissions
        # regardless of which caller (router, replay, retry) triggered them.
        if self._halted_reason is not None:
            return OrderResult(False, reason=f"trading halted: {self._halted_reason}")
        if order.client_order_id and self.repository.has_order_id(order.client_order_id):
            return OrderResult(True, order.client_order_id, "duplicate order already recorded")
        # Paper/backtest orders intentionally use their event timestamp. Live
        # orders must always be checked against the wall clock.
        if self.market_hours and not self.market_hours.is_open(
            order.timestamp if self.paper_trading else None
        ):
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
            # Falling back to timestamp alone collides whenever two symbols
            # replay the same tick timestamp; the broker_order_id must stay
            # unique per order the way a real broker's order number would be.
            order_id = order.client_order_id or (
                f"paper-{order.strategy_id}:{order.symbol}:{order.side.value}:"
                f"{order.timestamp.timestamp()}"
            )
            trade_id = self.repository.save(TradeLog(
                symbol=order.symbol, side=order.side, quantity=order.quantity,
                price=order.price, strategy_id=order.strategy_id,
                signal_strength=order.signal_strength, status="simulated",
                timestamp=order.timestamp, broker_order_id=order_id,
                client_order_id=order.client_order_id,
            ))
        else:
            client_id = order.client_order_id or (
                f"{order.strategy_id}:{order.symbol}:{order.side.value}:"
                f"{order.timestamp.isoformat()}"
            )
            self.repository.save(TradeLog(
                symbol=order.symbol, side=order.side, quantity=order.quantity,
                price=order.price, strategy_id=order.strategy_id,
                signal_strength=order.signal_strength, status="pending",
                timestamp=order.timestamp, broker_order_id=client_id,
                client_order_id=client_id,
            ))
            try:
                order_id = self.executor.submit(order)  # type: ignore[union-attr]
            except Exception:
                self.repository.update_order_status(client_id, "rejected")
                self._consecutive_rejections += 1
                if self._consecutive_rejections >= self.max_consecutive_rejections:
                    self._halted_reason = (
                        f"{self._consecutive_rejections} consecutive broker rejections"
                    )
                return OrderResult(False, reason="broker order submission failed")
            if not self.repository.attach_broker_order(client_id, order_id):
                raise RuntimeError("failed to attach broker order to pending record")
            trade_id = 0
        self._consecutive_rejections = 0
        if self.portfolio:
            self.portfolio.apply(order)
        return OrderResult(True, order_id or f"trade-{trade_id}")
