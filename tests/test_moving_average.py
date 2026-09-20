import pytest

from src.models import SignalAction, Tick
from src.strategies.moving_average import MovingAverageStrategy
from datetime import datetime, timezone

_TS = datetime(2026, 1, 1, tzinfo=timezone.utc)


def tick(price):
    return Tick(symbol="005930", price=price, volume=1, timestamp=_TS)


def test_strength_gain_must_be_positive():
    with pytest.raises(ValueError, match="strength_gain"):
        MovingAverageStrategy(strength_gain=0)


def test_default_gain_lets_a_real_world_spread_clear_a_060_threshold():
    """Regression test: the pre-2026-09-20 gain of 20 capped strength at
    ~0.507 on real recorded data (2026-09-09, 005930), so no signal could
    ever pass a MIN_SIGNAL_STRENGTH=0.60 risk gate. A gain of 300 (the new
    default) must let a realistic crossing spread (~0.0004, the largest
    observed at an actual crossing in that session) clear 0.60.
    """
    strategy = MovingAverageStrategy(short_window=2, long_window=3)
    for price in (100, 100, 100):
        strategy.on_tick(tick(price))

    signal = strategy.on_tick(tick(100.25))  # spread ~= 0.00042 at the crossing tick

    assert signal.action == SignalAction.BUY
    assert signal.strength >= 0.60


def test_higher_gain_produces_higher_strength_for_the_same_spread():
    low_gain = MovingAverageStrategy(short_window=2, long_window=3, strength_gain=20.0)
    high_gain = MovingAverageStrategy(short_window=2, long_window=3, strength_gain=300.0)
    prices = (100, 100, 100, 101)

    low_signal = high_signal = None
    for price in prices:
        low_signal = low_gain.on_tick(tick(price))
        high_signal = high_gain.on_tick(tick(price))

    assert low_signal.action == high_signal.action == SignalAction.BUY
    assert high_signal.strength > low_signal.strength


def test_strength_is_still_capped_at_one():
    strategy = MovingAverageStrategy(short_window=2, long_window=3, strength_gain=1_000_000.0)
    for price in (100, 100, 100):
        strategy.on_tick(tick(price))

    signal = strategy.on_tick(tick(200))

    assert signal.strength == 1.0
