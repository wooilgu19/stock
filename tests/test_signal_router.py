from src.engine.order_manager import OrderManager
from src.engine.risk import RiskGate
from src.engine.signal_router import SignalOrderRouter
from src.models import Signal, SignalAction, Side
from src.database.sqlite import TradeRepository


def make_router(tmp_path, quantity=2):
    repository = TradeRepository(tmp_path / "trades.sqlite3")
    manager = OrderManager(
        repository,
        RiskGate(min_signal_strength=0.6, max_order_value=1_000_000, max_daily_loss=100_000),
    )
    return SignalOrderRouter(manager, quantity=quantity), repository


def signal(action, strength=0.8):
    return Signal("005930", action, strength, 70_000, "baseline")


def test_buy_signal_becomes_paper_order(tmp_path):
    router, repository = make_router(tmp_path)

    result = router.route(signal(SignalAction.BUY))

    assert result is not None
    assert result.accepted
    assert result.order_id.startswith("paper-")
    with repository._connect() as connection:
        row = connection.execute("SELECT side, quantity, status FROM trade_logs").fetchone()
    assert (row["side"], row["quantity"], row["status"]) == (Side.BUY.value, 2, "simulated")


def test_hold_signal_does_not_submit_order(tmp_path):
    router, repository = make_router(tmp_path)

    assert router.route(signal(SignalAction.HOLD, strength=0.0)) is None
    with repository._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM trade_logs").fetchone()[0] == 0


def test_router_supports_symbol_specific_quantity(tmp_path):
    router, _ = make_router(tmp_path, {"005930": 3})

    result = router.route(signal(SignalAction.SELL))

    assert result is not None and result.accepted


def test_router_rejects_unknown_symbol_quantity(tmp_path):
    router, _ = make_router(tmp_path, {"000660": 1})

    try:
        router.route(signal(SignalAction.BUY))
    except ValueError as exc:
        assert "005930" in str(exc)
    else:
        raise AssertionError("unknown symbol quantity was accepted")
