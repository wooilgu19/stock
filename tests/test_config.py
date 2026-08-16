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
