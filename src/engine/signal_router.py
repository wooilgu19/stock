"""Translate strategy signals into risk-checked order requests.

The router deliberately knows nothing about broker APIs.  This keeps the
inference pipeline usable in paper trading while making the hand-off to
``OrderManager`` explicit and testable.
"""

from collections.abc import Callable, Mapping
from datetime import time
from zoneinfo import ZoneInfo

from src.engine.order_manager import OrderManager, OrderResult
from src.models import OrderRequest, Signal, SignalAction, Side

FLATTEN_STRATEGY_ID = "eod-flatten"


class SignalOrderRouter:
    """Convert actionable signals into orders with symbol-specific sizing.

    With ``flatten_after`` set, every signal at or after that local time
    stops opening positions: buys are dropped and each paper holding is sold
    at its last seen price, so no position is carried into the next day.
    """

    def __init__(
        self,
        order_manager: OrderManager,
        quantity: int | Mapping[str, int] = 1,
        on_result: Callable[[Signal, OrderResult], None] | None = None,
        automation_enabled: bool = True,
        flatten_after: time | None = None,
        timezone_name: str = "Asia/Seoul",
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
        self.automation_enabled = automation_enabled
        self.flatten_after = flatten_after
        self.timezone = ZoneInfo(timezone_name)
        self._last_prices: dict[str, float] = {}

    def _in_flatten_window(self, signal: Signal) -> bool:
        if self.flatten_after is None:
            return False
        return signal.timestamp.astimezone(self.timezone).time() >= self.flatten_after

    def _flatten(self, signal: Signal) -> OrderResult | None:
        """Sell every held symbol whose price has been seen this session.

        Orders are chunked to stay under the risk gate's order value cap; a
        rejected chunk is retried on the next signal since the position is
        still there.
        """
        portfolio = self.order_manager.portfolio
        if portfolio is None:
            return None
        max_value = self.order_manager.risk_gate.max_order_value
        result = None
        for symbol, held in list(portfolio.positions.items()):
            price = self._last_prices.get(symbol)
            if price is None or held <= 0:
                continue
            chunk = max(1, int(max_value // price))
            index = 0
            while portfolio.positions.get(symbol, 0) > 0:
                exit_signal = Signal(symbol, SignalAction.SELL, 1.0, price,
                                     FLATTEN_STRATEGY_ID, signal.timestamp)
                order = OrderRequest(
                    symbol=symbol, side=Side.SELL,
                    quantity=min(chunk, portfolio.positions[symbol]),
                    price=price, strategy_id=FLATTEN_STRATEGY_ID, signal_strength=1.0,
                    timestamp=signal.timestamp,
                    client_order_id=(
                        f"{FLATTEN_STRATEGY_ID}:{symbol}:{signal.timestamp.isoformat()}:{index}"
                    ),
                )
                result = self.order_manager.submit(order)
                if self.on_result:
                    self.on_result(exit_signal, result)
                # A duplicate (replayed tick) is "accepted" without touching
                # the portfolio, so it must stop the loop as well.
                if not result.accepted or result.reason:
                    break
                index += 1
        return result

    def _quantity_for(self, symbol: str) -> int:
        if isinstance(self.quantity, int):
            return self.quantity
        try:
            return self.quantity[symbol]
        except KeyError as exc:
            raise ValueError(f"no order quantity configured for {symbol}") from exc

    def route(self, signal: Signal) -> OrderResult | None:
        if signal.price > 0:
            self._last_prices[signal.symbol] = signal.price
        if not self.automation_enabled:
            return None
        if self._in_flatten_window(signal):
            return self._flatten(signal)
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
            client_order_id=(
                f"{signal.strategy_id}:{signal.symbol}:{signal.action.value}:"
                f"{signal.timestamp.isoformat()}"
            ),
        )
        result = self.order_manager.submit(order)
        if self.on_result:
            self.on_result(signal, result)
        return result
