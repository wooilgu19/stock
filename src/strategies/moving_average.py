"""Small, deterministic moving-average strategy for pipeline validation."""

from collections import defaultdict, deque
from collections.abc import Iterable

from src.models import Signal, SignalAction, Tick


class MovingAverageStrategy:
    def __init__(self, short_window: int = 5, long_window: int = 20,
                 strategy_id: str = "moving-average") -> None:
        if short_window <= 0 or long_window <= short_window:
            raise ValueError("long_window must be greater than short_window")
        self.short_window = short_window
        self.long_window = long_window
        self.strategy_id = strategy_id
        self._prices: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=self.long_window)
        )

    def on_tick(self, tick: Tick) -> Signal:
        prices = self._prices[tick.symbol]
        previous_short = sum(list(prices)[-self.short_window:]) / min(len(prices), self.short_window) if prices else tick.price
        prices.append(tick.price)
        if len(prices) < self.long_window:
            return Signal(tick.symbol, SignalAction.HOLD, 0.0, tick.price, self.strategy_id)

        short_average = sum(list(prices)[-self.short_window:]) / self.short_window
        long_average = sum(prices) / self.long_window
        spread = abs(short_average - long_average) / long_average
        strength = min(1.0, 0.5 + spread * 20)
        if short_average > long_average and previous_short <= long_average:
            action = SignalAction.BUY
        elif short_average < long_average and previous_short >= long_average:
            action = SignalAction.SELL
        else:
            action = SignalAction.HOLD
        return Signal(tick.symbol, action, strength if action != SignalAction.HOLD else 0.0,
                      tick.price, self.strategy_id)
