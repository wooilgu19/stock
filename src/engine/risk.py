"""Pre-trade risk checks."""

from dataclasses import dataclass

from src.models import OrderRequest


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reason: str = "approved"


class RiskGate:
    def __init__(self, min_signal_strength: float, max_order_value: int, max_daily_loss: int) -> None:
        self.min_signal_strength = min_signal_strength
        self.max_order_value = max_order_value
        self.max_daily_loss = max_daily_loss

    def check(self, order: OrderRequest, daily_loss: float = 0) -> RiskDecision:
        if order.signal_strength < self.min_signal_strength:
            return RiskDecision(False, "signal strength is below the minimum")
        if order.value > self.max_order_value:
            return RiskDecision(False, "order value exceeds the limit")
        if daily_loss >= self.max_daily_loss:
            return RiskDecision(False, "daily loss limit has been reached")
        return RiskDecision(True)
