from src.application import build_reconciler
from src.config import Settings


def test_paper_mode_does_not_create_broker_reconciler(tmp_path):
    reconciler = build_reconciler(
        Settings(database_path=tmp_path / "trades.sqlite3", paper_trading=True)
    )

    assert reconciler is None


def test_live_mode_creates_reconciler_without_network_call(tmp_path):
    reconciler = build_reconciler(Settings(
        database_path=tmp_path / "trades.sqlite3",
        paper_trading=False,
        kis_cano="12345678",
        kis_appkey="key",
        kis_appsecret="secret",
    ))

    assert reconciler is not None
    assert reconciler.repository.pending_order_ids() == set()


def test_live_reconciler_uses_configured_order_lookback(tmp_path):
    reconciler = build_reconciler(Settings(
        database_path=tmp_path / "trades.sqlite3",
        paper_trading=False,
        kis_cano="12345678",
        kis_appkey="key",
        kis_appsecret="secret",
        kis_order_lookback_days=5,
    ))

    assert reconciler is not None
    assert reconciler.fetch_updates.lookback_days == 5
