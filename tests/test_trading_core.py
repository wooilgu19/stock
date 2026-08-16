from datetime import date, datetime, timezone

from src.database.sqlite import TradeRepository
from src.models import OrderRequest, Side, Tick, TradeLog


def test_daily_realized_loss_excludes_other_days(tmp_path):
    repository = TradeRepository(tmp_path / "trades.sqlite3")
    for day, price in ((date(2026, 8, 13), 100), (date(2026, 8, 14), 250)):
        repository.save(TradeLog(
            symbol="005930", side=Side.SELL, quantity=1, price=price,
            strategy_id="test", signal_strength=0.8, status="loss",
            timestamp=datetime(day.year, day.month, day.day, 2, tzinfo=timezone.utc),
        ))

    assert repository.daily_realized_loss(date(2026, 8, 14)) == 250


def test_trade_timestamps_are_normalized_to_utc():
    naive_tick = Tick("005930", 100, 1, datetime(2026, 8, 14, 9))
    local_order = OrderRequest(
        "005930", Side.BUY, 1, 100, "test", 0.8,
        timestamp=datetime(2026, 8, 14, 9),
    )

    assert naive_tick.timestamp.tzinfo is timezone.utc
    assert local_order.timestamp.tzinfo is timezone.utc
from src.engine.order_manager import OrderManager
from src.engine.risk import RiskGate
from src.models import OrderRequest, Side, Tick


def make_manager(tmp_path):
    repository = TradeRepository(tmp_path / "trades.sqlite3")
    gate = RiskGate(min_signal_strength=0.6, max_order_value=1_000_000, max_daily_loss=100_000)
    return OrderManager(repository, gate)


def test_tick_rejects_invalid_price():
    try:
        Tick(symbol="005930", price=0, volume=1)
    except ValueError as exc:
        assert "price" in str(exc)
    else:
        raise AssertionError("invalid tick was accepted")


def test_order_is_saved_in_paper_mode(tmp_path):
    manager = make_manager(tmp_path)
    result = manager.submit(OrderRequest("005930", Side.BUY, 2, 70_000, "baseline", 0.8))
    assert result.accepted
    assert result.order_id.startswith("paper-")


def test_weak_signal_is_rejected(tmp_path):
    manager = make_manager(tmp_path)
    result = manager.submit(OrderRequest("005930", Side.BUY, 1, 70_000, "baseline", 0.4))
    assert not result.accepted
    assert "strength" in result.reason


def test_order_rejects_invalid_signal_strength():
    try:
        OrderRequest("005930", Side.BUY, 1, 70_000, "baseline", 1.1)
    except ValueError as exc:
        assert "signal_strength" in str(exc)
    else:
        raise AssertionError("invalid signal strength was accepted")
