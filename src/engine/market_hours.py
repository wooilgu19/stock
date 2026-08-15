"""Basic KRX cash-market session check.

This intentionally covers regular weekdays and hours only. Exchange holiday
calendars should be added before enabling live order submission.
"""

from collections.abc import Iterable
from datetime import date, datetime, time
from zoneinfo import ZoneInfo


class MarketHours:
    def __init__(
        self,
        timezone_name: str = "Asia/Seoul",
        open_time: time = time(9, 0),
        close_time: time = time(15, 30),
        holidays: Iterable[date] = (),
    ) -> None:
        if open_time >= close_time:
            raise ValueError("open_time must be earlier than close_time")
        self.timezone = ZoneInfo(timezone_name)
        self.open_time = open_time
        self.close_time = close_time
        self.holidays = frozenset(holidays)

    def is_open(self, when: datetime) -> bool:
        local = when.astimezone(self.timezone) if when.tzinfo else when.replace(tzinfo=self.timezone)
        return (
            local.weekday() < 5
            and local.date() not in self.holidays
            and self.open_time <= local.time() < self.close_time
        )
