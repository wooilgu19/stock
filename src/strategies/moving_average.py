"""Small, deterministic moving-average strategy for pipeline validation."""

from collections import defaultdict, deque

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
        self._previous_short: dict[str, float] = {}
        self._previous_long: dict[str, float] = {}

    def on_tick(self, tick: Tick) -> Signal:
        prices = self._prices[tick.symbol]
        prices.append(tick.price)
        if len(prices) < self.long_window:
            return Signal(tick.symbol, SignalAction.HOLD, 0.0, tick.price, self.strategy_id)

        short_average = sum(list(prices)[-self.short_window:]) / self.short_window
        long_average = sum(prices) / self.long_window
        spread = abs(short_average - long_average) / long_average
        strength = min(1.0, 0.5 + spread * 20)
        previous_short = self._previous_short.get(tick.symbol, short_average)
        previous_long = self._previous_long.get(tick.symbol, long_average)
        if short_average > long_average and previous_short <= previous_long:
            action = SignalAction.BUY
        elif short_average < long_average and previous_short >= previous_long:
            action = SignalAction.SELL
        else:
            action = SignalAction.HOLD
        self._previous_short[tick.symbol] = short_average
        self._previous_long[tick.symbol] = long_average
        return Signal(tick.symbol, action, strength if action != SignalAction.HOLD else 0.0,
                      tick.price, self.strategy_id)
