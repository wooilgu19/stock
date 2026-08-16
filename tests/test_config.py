import pytest

from src.config import Settings


def test_automation_mode_defaults_to_auto():
    settings = Settings()

    assert settings.automation_mode == "auto"
    assert settings.automation_enabled is True


def test_invalid_automation_mode_is_rejected():
    with pytest.raises(ValueError, match="automation_mode"):
        Settings(automation_mode="scheduled")


def test_manual_automation_mode_is_available_without_disabling_paper_trading():
    settings = Settings(automation_mode="manual", paper_trading=True)

    assert settings.automation_enabled is False
    assert settings.paper_trading is True


def test_order_status_lookback_must_be_positive():
    with pytest.raises(ValueError, match="kis_order_lookback_days"):
        Settings(kis_order_lookback_days=0)


def test_paper_starting_cash_cannot_be_negative():
    with pytest.raises(ValueError, match="paper_starting_cash"):
        Settings(paper_starting_cash=-1)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("min_signal_strength", 1.1, "min_signal_strength"),
        ("max_order_value", -1, "max_order_value"),
        ("max_daily_loss", -1, "max_daily_loss"),
    ],
)
def test_settings_reject_invalid_risk_limits(field, value, message):
    with pytest.raises(ValueError, match=message):
        Settings(**{field: value})


def test_telegram_settings_must_be_configured_together():
    with pytest.raises(ValueError, match="telegram_token"):
        Settings(telegram_token="token")


def test_telegram_enabled_requires_both_credentials():
    settings = Settings(telegram_token="token", telegram_chat_id="chat")

    assert settings.telegram_enabled is True
