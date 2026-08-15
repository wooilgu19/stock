"""Parsing utilities for operator-supplied exchange holiday dates."""

from datetime import date


def parse_holiday_dates(value: str) -> frozenset[date]:
    """Parse comma-separated ISO dates such as ``2026-01-01,2026-03-02``."""
    holidays: set[date] = set()
    for raw_item in value.split(","):
        item = raw_item.strip()
        if not item:
            continue
        try:
            holidays.add(date.fromisoformat(item))
        except ValueError as exc:
            raise ValueError(f"invalid holiday date: {item}") from exc
    return frozenset(holidays)
