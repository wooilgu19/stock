from datetime import datetime, timezone

from src.database.sqlite import TradeRepository
from src.engine.reconciliation import OrderReconciler
from src.models import OrderRequest, OrderStatusUpdate, Side, TradeLog


def test_reconciler_updates_known_submitted_orders_and_ignores_unknown(tmp_path):
    repository = TradeRepository(tmp_path / "trades.sqlite3")
    repository.save(TradeLog(
        symbol="005930", side=Side.BUY, quantity=1, price=70000,
        strategy_id="baseline", signal_strength=0.8, status="submitted",
        broker_order_id="kis-1", timestamp=datetime.now(timezone.utc),
    ))
    reconciler = OrderReconciler(repository, lambda: [
        OrderStatusUpdate("kis-1", "filled"),
        OrderStatusUpdate("kis-unknown", "filled"),
    ])

    result = reconciler.reconcile()

    assert result == type(result)(updated=1, ignored=1)
    assert repository.pending_order_ids() == set()
    with repository._connect() as connection:
        assert connection.execute(
            "SELECT status FROM trade_logs WHERE broker_order_id = 'kis-1'"
        ).fetchone()[0] == "filled"


def test_reconciler_does_not_reapply_terminal_order(tmp_path):
    repository = TradeRepository(tmp_path / "trades.sqlite3")
    repository.save(TradeLog(
        symbol="005930", side=Side.BUY, quantity=1, price=70000,
        strategy_id="baseline", signal_strength=0.8, status="filled",
        broker_order_id="kis-1",
    ))
    result = OrderReconciler(
        repository, lambda: [OrderStatusUpdate("kis-1", "cancelled")]
    ).reconcile()

    assert result.updated == 0
    assert result.ignored == 1


def test_reconciler_keeps_submitted_order_pending_until_terminal(tmp_path):
    repository = TradeRepository(tmp_path / "trades.sqlite3")
    repository.save(TradeLog(
        symbol="005930", side=Side.BUY, quantity=1, price=70000,
        strategy_id="baseline", signal_strength=0.8, status="submitted",
        broker_order_id="kis-1",
    ))
    reconciler = OrderReconciler(repository, lambda: [
        OrderStatusUpdate("kis-1", "submitted"),
    ])

    result = reconciler.reconcile()

    assert result == type(result)(updated=1, ignored=0)
    assert repository.pending_order_ids() == {"kis-1"}
