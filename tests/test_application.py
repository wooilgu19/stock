from datetime import date

import pytest

from src.application import build_order_manager
from src.config import Settings


def test_build_order_manager_defaults_to_paper_mode(tmp_path):
    manager = build_order_manager(Settings(database_path=tmp_path / "trades.sqlite3"))

    assert manager.paper_trading is True
    assert manager.executor is None
    assert manager.market_hours is not None


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
    assert date(2026, 8, 14) in manager.market_hours.holidays
