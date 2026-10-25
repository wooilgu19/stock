from datetime import datetime, time, timedelta, timezone

import pytest

from src.config import parse_flatten_time
from src.database.sqlite import TradeRepository
from src.engine.order_manager import OrderManager
from src.engine.portfolio import PortfolioState
from src.engine.risk import RiskGate
from src.engine.signal_router import FLATTEN_STRATEGY_ID, SignalOrderRouter
from src.models import OrderRequest, Side, Signal, SignalAction

KST = timezone(timedelta(hours=9))
DAY = datetime(2026, 10, 26, tzinfo=KST)  # a Monday


def at(hour, minute=0, second=0):
    return DAY.replace(hour=hour, minute=minute, second=second)


def make_manager(tmp_path, max_daily_loss=100_000):
    repository = TradeRepository(tmp_path / "trades.sqlite3")
    manager = OrderManager(
        repository,
        RiskGate(0.6, 1_000_000, max_daily_loss),
        portfolio=PortfolioState(cash=10_000_000),
    )
    return manager, repository


def sell_order(quantity, when, order_id):
    return OrderRequest("005930", Side.SELL, quantity, 200_000, "baseline", 0.8,
                        timestamp=when, client_order_id=order_id)


def test_risk_gate_lets_position_reducing_sell_through_daily_loss_limit():
    gate = RiskGate(0.6, 1_000_000, 100_000)
    order = sell_order(1, at(10), "s")

    assert not gate.check(order, daily_loss=100_000).allowed
    assert gate.check(order, daily_loss=100_000, reduces_position=True).allowed


def test_reducing_sell_still_respects_strength_and_value_limits():
    gate = RiskGate(0.6, 1_000_000, 100_000)
    weak = OrderRequest("005930", Side.SELL, 1, 200_000, "baseline", 0.5)
    large = OrderRequest("005930", Side.SELL, 10, 200_000, "baseline", 0.8)

    assert gate.check(weak, 100_000, reduces_position=True).reason == "signal strength is below the minimum"
    assert gate.check(large, 100_000, reduces_position=True).reason == "order value exceeds the limit"


def test_order_manager_allows_exit_but_not_entry_after_loss_limit(tmp_path):
    manager, _ = make_manager(tmp_path, max_daily_loss=0)  # limit already reached
    manager.portfolio.positions["005930"] = 2

    buy = OrderRequest("005930", Side.BUY, 1, 200_000, "baseline", 0.8,
                       timestamp=at(10), client_order_id="b")
    assert manager.submit(buy).reason == "daily loss limit has been reached"

    assert manager.submit(sell_order(2, at(10), "s1")).accepted
    assert manager.portfolio.positions == {}
    # Nothing left to reduce, so a further sell is new risk again.
    assert manager.submit(sell_order(1, at(10), "s2")).reason == "daily loss limit has been reached"


def test_simulated_orders_use_their_own_day_for_the_loss_limit(tmp_path):
    manager, _ = make_manager(tmp_path, max_daily_loss=1_000)
    past = datetime(2026, 10, 23, 10, tzinfo=KST)  # a replayed day, not today
    for order_id, side, price in (("b", Side.BUY, 200_000), ("s", Side.SELL, 198_000)):
        assert manager.submit(OrderRequest("005930", side, 1, price, "baseline", 0.8,
                                           timestamp=past, client_order_id=order_id)).accepted

    later_buy = OrderRequest("005930", Side.BUY, 1, 200_000, "baseline", 0.8,
                             timestamp=past.replace(hour=11), client_order_id="b2")
    assert manager.submit(later_buy).reason == "daily loss limit has been reached"


def test_oversized_sell_is_not_treated_as_reducing(tmp_path):
    manager, _ = make_manager(tmp_path, max_daily_loss=0)
    manager.portfolio.positions["005930"] = 1

    assert manager.submit(sell_order(2, at(10), "s")).reason == "daily loss limit has been reached"


def make_router(manager, results=None, flatten_after=time(19, 50)):
    def record(signal, result):
        if results is not None:
            results.append((signal, result))
    return SignalOrderRouter(manager, on_result=record, flatten_after=flatten_after)


def test_flatten_window_sells_all_holdings_in_value_capped_chunks(tmp_path):
    manager, repository = make_manager(tmp_path)
    results = []
    router = make_router(manager, results)
    manager.portfolio.positions.update({"005930": 9, "000660": 1})

    router.route(Signal("000660", SignalAction.HOLD, 0.0, 900_000, "baseline", at(15, 30)))
    router.route(Signal("005930", SignalAction.HOLD, 0.0, 210_000, "baseline", at(19, 49)))
    assert manager.portfolio.positions == {"005930": 9, "000660": 1}  # not yet

    router.route(Signal("005930", SignalAction.HOLD, 0.0, 200_000, "baseline", at(19, 50)))

    assert manager.portfolio.positions == {}
    with repository._connect() as connection:
        rows = connection.execute(
            "SELECT symbol, side, quantity, price, strategy_id FROM trade_logs ORDER BY id"
        ).fetchall()
    # 1,000,000 cap / 200,000 = 5 shares per order; 000660 uses its last price.
    assert [tuple(row) for row in rows] == [
        ("005930", "sell", 5, 200_000.0, FLATTEN_STRATEGY_ID),
        ("005930", "sell", 4, 200_000.0, FLATTEN_STRATEGY_ID),
        ("000660", "sell", 1, 900_000.0, FLATTEN_STRATEGY_ID),
    ]
    assert all(result.accepted for _, result in results)
    assert all(signal.strategy_id == FLATTEN_STRATEGY_ID for signal, _ in results)


def test_flatten_window_drops_new_buys(tmp_path):
    manager, repository = make_manager(tmp_path)
    router = make_router(manager)

    assert router.route(Signal("005930", SignalAction.BUY, 0.9, 200_000, "baseline", at(19, 55))) is None
    assert manager.portfolio.positions == {}
    with repository._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM trade_logs").fetchone()[0] == 0


def test_flatten_ignores_holdings_without_a_seen_price(tmp_path):
    manager, _ = make_manager(tmp_path)
    router = make_router(manager)
    manager.portfolio.positions["009830"] = 3  # carried from a day it wasn't subscribed

    router.route(Signal("005930", SignalAction.HOLD, 0.0, 200_000, "baseline", at(19, 55)))

    assert manager.portfolio.positions == {"009830": 3}


def test_flatten_disabled_trades_normally_late(tmp_path):
    manager, _ = make_manager(tmp_path)
    router = make_router(manager, flatten_after=None)

    result = router.route(Signal("005930", SignalAction.BUY, 0.9, 200_000, "baseline", at(19, 55)))

    assert result is not None and result.accepted
    assert manager.portfolio.positions == {"005930": 1}


def test_flatten_window_compares_in_kst_for_utc_signals(tmp_path):
    manager, _ = make_manager(tmp_path)
    router = make_router(manager)
    manager.portfolio.positions["005930"] = 1
    utc_19_50_kst = at(19, 50).astimezone(timezone.utc)  # 10:50 UTC

    router.route(Signal("005930", SignalAction.HOLD, 0.0, 200_000, "baseline", utc_19_50_kst))

    assert manager.portfolio.positions == {}


def test_parse_flatten_time():
    assert parse_flatten_time("19:50") == time(19, 50)
    assert parse_flatten_time(" off ") is None
    assert parse_flatten_time("") is None
    with pytest.raises(ValueError, match="EOD_FLATTEN_TIME"):
        parse_flatten_time("7pm")
