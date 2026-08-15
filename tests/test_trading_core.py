from src.database.sqlite import TradeRepository
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
