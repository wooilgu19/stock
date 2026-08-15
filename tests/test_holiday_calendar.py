from datetime import date

import pytest

from src.config import Settings
from src.engine.holiday_calendar import parse_holiday_dates


def test_holiday_parser_accepts_csv_dates():
    assert parse_holiday_dates("2026-01-01, 2026-03-02") == frozenset({
        date(2026, 1, 1), date(2026, 3, 2),
    })


def test_holiday_parser_ignores_empty_items():
    assert parse_holiday_dates("") == frozenset()
    assert parse_holiday_dates("2026-01-01,,") == frozenset({date(2026, 1, 1)})


def test_holiday_parser_rejects_non_iso_date():
    with pytest.raises(ValueError, match="invalid holiday date"):
        parse_holiday_dates("2026/01/01")


def test_settings_exposes_holiday_configuration():
    assert hasattr(Settings(), "market_holidays")
