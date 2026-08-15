from datetime import date, datetime, time, timezone

from src.database.sqlite import TradeRepository
from src.engine.market_hours import MarketHours
from src.engine.order_manager import OrderManager
from src.engine.risk import RiskGate
from src.models import OrderRequest, Side


def make_order(timestamp, order_id="order-1"):
    return OrderRequest(
        "005930", Side.BUY, 1, 70_000, "baseline", 0.8,
        timestamp=timestamp, client_order_id=order_id,
    )


def make_manager(tmp_path, market_hours=None):
    return OrderManager(
        TradeRepository(tmp_path / "trades.sqlite3"),
        RiskGate(0.6, 1_000_000, 100_000),
        market_hours=market_hours,
    )


def test_duplicate_client_order_is_not_saved_twice(tmp_path):
    manager = make_manager(tmp_path)
    timestamp = datetime(2026, 8, 14, 2, 0, tzinfo=timezone.utc)

    first = manager.submit(make_order(timestamp))
    second = manager.submit(make_order(timestamp))

    assert first.accepted and second.accepted
    assert second.reason == "duplicate order already recorded"
    with manager.repository._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM trade_logs").fetchone()[0] == 1


def test_market_hours_reject_weekend_and_accept_session(tmp_path):
    session = MarketHours()
    manager = make_manager(tmp_path, session)

    weekend = datetime(2026, 8, 15, 2, 0, tzinfo=timezone.utc)
    weekday_open = datetime(2026, 8, 14, 1, 0, tzinfo=timezone.utc)

    assert not session.is_open(weekend)
    assert session.is_open(weekday_open)
    assert manager.submit(make_order(weekend)).reason == "market is closed"
    assert manager.submit(make_order(weekday_open)).accepted


def test_market_hours_rejects_invalid_session():
    try:
        MarketHours(open_time=time(15, 30), close_time=time(9, 0))
    except ValueError as exc:
        assert "earlier" in str(exc)
    else:
        raise AssertionError("invalid session was accepted")


def test_market_hours_rejects_configured_holiday():
    session = MarketHours(holidays={date(2026, 8, 14)})
    session_time = datetime(2026, 8, 14, 1, 0, tzinfo=timezone.utc)

    assert not session.is_open(session_time)
