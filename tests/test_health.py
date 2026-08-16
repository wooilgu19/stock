from src.database.sqlite import TradeRepository
from src.monitoring.health import HealthMonitor


def test_health_monitor_reports_database_and_queue_status(tmp_path):
    calls = []
    monitor = HealthMonitor(
        TradeRepository(tmp_path / "trades.sqlite3"),
        queue_probe=lambda: calls.append("ping"),
    )

    report = monitor.check()

    assert report.healthy
    assert calls == ["ping"]
    assert report.checks["database"].ok
    assert report.as_dict()["healthy"] is True


def test_health_monitor_reports_queue_failure_without_raising(tmp_path):
    def failing_probe():
        raise ConnectionError("redis unavailable")

    report = HealthMonitor(
        TradeRepository(tmp_path / "trades.sqlite3"), failing_probe
    ).check()

    assert not report.healthy
    assert not report.checks["queue"].ok
    assert "redis unavailable" in report.checks["queue"].detail
