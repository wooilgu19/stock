from datetime import date, datetime, timezone

import pytest

from src.application import build_order_manager
from src.config import Settings


def test_build_order_manager_defaults_to_paper_mode(tmp_path):
    manager = build_order_manager(Settings(
        database_path=tmp_path / "trades.sqlite3", paper_starting_cash=500_000,
    ))

    assert manager.paper_trading is True
    assert manager.executor is None
    assert manager.market_hours is not None
    assert manager.portfolio is not None
    assert manager.portfolio.cash == 500_000


def test_paper_portfolio_is_restored_from_repository(tmp_path):
    settings = Settings(
        database_path=tmp_path / "trades.sqlite3", paper_starting_cash=500_000,
    )
    first = build_order_manager(settings)
    from src.models import OrderRequest, Side

    assert first.submit(OrderRequest(
        "005930", Side.BUY, 2, 70_000, "test", 0.8,
        timestamp=datetime(2026, 8, 14, 1, 0, tzinfo=timezone.utc),
    )).accepted

    restored = build_order_manager(settings)

    assert restored.portfolio is not None
    assert restored.portfolio.cash == 360_000
    assert restored.portfolio.positions == {"005930": 2}


def test_live_build_requires_credentials_before_network_usage(tmp_path):
    settings = Settings(
        database_path=tmp_path / "trades.sqlite3",
        paper_trading=False,
        kis_cano="",
        kis_appkey="key",
        kis_appsecret="secret",
    )

    with pytest.raises(ValueError, match="KIS_CANO"):
        build_order_manager(settings)


def test_live_build_injects_executor_without_network_call(tmp_path):
    settings = Settings(
        database_path=tmp_path / "trades.sqlite3",
        paper_trading=False,
        kis_cano="12345678",
        kis_appkey="key",
        kis_appsecret="secret",
        market_holidays=frozenset({date(2026, 8, 14)}),
    )

    manager = build_order_manager(settings)

    assert manager.paper_trading is False
    assert manager.executor is not None
    assert manager.portfolio is None
    assert date(2026, 8, 14) in manager.market_hours.holidays


def test_build_order_manager_skips_market_hours_check_when_disabled(tmp_path):
    manager = build_order_manager(
        Settings(database_path=tmp_path / "trades.sqlite3", paper_starting_cash=500_000),
        enforce_market_hours=False,
    )

    assert manager.market_hours is None


def test_build_order_manager_enforces_market_hours_by_default(tmp_path):
    manager = build_order_manager(
        Settings(database_path=tmp_path / "trades.sqlite3", paper_starting_cash=500_000),
    )

    assert manager.market_hours is not None
