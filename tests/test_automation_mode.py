from datetime import datetime, timezone

from src.application import build_signal_router
from src.config import Settings
from src.database.sqlite import TradeRepository
from src.engine.order_manager import OrderManager
from src.engine.risk import RiskGate
from src.models import Signal, SignalAction


def make_signal():
    return Signal(
        symbol="005930", action=SignalAction.BUY, strength=0.9, price=70000,
        strategy_id="baseline", timestamp=datetime(2026, 8, 14, 1, 0, tzinfo=timezone.utc),
    )


def make_manager(tmp_path):
    return OrderManager(
        TradeRepository(tmp_path / "trades.sqlite3"),
        RiskGate(0.6, 1_000_000, 100_000),
    )


def test_manual_mode_drops_actionable_signal(tmp_path):
    router = build_signal_router(
        Settings(automation_mode="manual", database_path=tmp_path / "unused.sqlite3"),
        make_manager(tmp_path),
    )

    assert router.route(make_signal()) is None
    assert router.order_manager.repository.pending_order_ids() == set()


def test_auto_mode_routes_actionable_signal(tmp_path):
    router = build_signal_router(
        Settings(automation_mode="auto", database_path=tmp_path / "unused.sqlite3"),
        make_manager(tmp_path),
    )

    result = router.route(make_signal())

    assert result is not None and result.accepted
