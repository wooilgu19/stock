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


def _paper_orders_settings(tmp_path, **overrides):
    values = dict(
        database_path=tmp_path / "trades.sqlite3", paper_starting_cash=500_000,
        kis_paper_orders=True, kis_paper_cano="50123456",
        kis_paper_appkey="pkey", kis_paper_appsecret="psecret",
    )
    values.update(overrides)
    return Settings(**values)


def test_paper_orders_inject_vts_executor_and_keep_portfolio(tmp_path):
    manager = build_order_manager(_paper_orders_settings(tmp_path))

    assert manager.executor is not None
    assert manager.executor.paper_trading is True
    assert manager.executor.account_number == "50123456"
    assert manager.executor.client.base_url == "https://openapivts.koreainvestment.com:29443"
    assert manager.executor.client.app_key == "pkey"
    assert manager.portfolio is not None


def test_paper_orders_require_credentials(tmp_path):
    with pytest.raises(ValueError, match="KIS_PAPER_APPKEY"):
        build_order_manager(_paper_orders_settings(tmp_path, kis_paper_appkey=""))


def test_paper_orders_refuse_real_server_url(tmp_path):
    settings = _paper_orders_settings(
        tmp_path, kis_paper_base_url="https://openapi.koreainvestment.com:9443")

    with pytest.raises(ValueError, match="openapivts"):
        build_order_manager(settings)


def test_paper_orders_flag_rejected_in_live_mode(tmp_path):
    with pytest.raises(ValueError, match="requires paper mode"):
        Settings(database_path=tmp_path / "t.sqlite3", paper_trading=False,
                 kis_paper_orders=True)


def test_paper_orders_are_sent_to_broker_with_vttc_tr_id(tmp_path):
    from src.models import OrderRequest, Side

    sent = []

    class FakeExecutor:
        def submit(self, order):
            sent.append(order)
            return "0000012345"

    manager = build_order_manager(_paper_orders_settings(tmp_path))
    manager.executor = FakeExecutor()
    manager.market_hours = None

    result = manager.submit(OrderRequest("005930", Side.BUY, 1, 70_000, "t", 0.8))

    assert result.accepted and result.order_id == "0000012345"
    assert len(sent) == 1


def test_paper_orders_reconciler_uses_paper_provider(tmp_path):
    from src.application import build_reconciler

    reconciler = build_reconciler(_paper_orders_settings(tmp_path))

    assert reconciler is not None
    assert reconciler.fetch_updates.paper_trading is True
