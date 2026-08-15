"""Translate strategy signals into risk-checked order requests.

The router deliberately knows nothing about broker APIs.  This keeps the
inference pipeline usable in paper trading while making the hand-off to
``OrderManager`` explicit and testable.
"""

from collections.abc import Callable, Mapping

from src.engine.order_manager import OrderManager, OrderResult
from src.models import OrderRequest, Signal, SignalAction, Side


class SignalOrderRouter:
    """Convert actionable signals into orders with symbol-specific sizing."""

    def __init__(
        self,
        order_manager: OrderManager,
        quantity: int | Mapping[str, int] = 1,
        on_result: Callable[[Signal, OrderResult], None] | None = None,
    ) -> None:
        if isinstance(quantity, int):
            if quantity <= 0:
                raise ValueError("quantity must be positive")
        elif not quantity:
            raise ValueError("quantity mapping cannot be empty")
        elif any(value <= 0 for value in quantity.values()):
            raise ValueError("quantities must be positive")

        self.order_manager = order_manager
        self.quantity = quantity
        self.on_result = on_result

    def _quantity_for(self, symbol: str) -> int:
        if isinstance(self.quantity, int):
            return self.quantity
        try:
            return self.quantity[symbol]
        except KeyError as exc:
            raise ValueError(f"no order quantity configured for {symbol}") from exc

    def route(self, signal: Signal) -> OrderResult | None:
        if signal.action == SignalAction.HOLD:
            return None

        side = Side.BUY if signal.action == SignalAction.BUY else Side.SELL
        order = OrderRequest(
            symbol=signal.symbol,
            side=side,
            quantity=self._quantity_for(signal.symbol),
            price=signal.price,
            strategy_id=signal.strategy_id,
            signal_strength=signal.strength,
            timestamp=signal.timestamp,
        )
        result = self.order_manager.submit(order)
        if self.on_result:
            self.on_result(signal, result)
        return result
