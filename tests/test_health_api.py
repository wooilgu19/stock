from fastapi import Response

from src.api.health import create_health_app
from src.database.sqlite import TradeRepository
from src.monitoring.health import HealthMonitor
from src.monitoring.metrics import RuntimeMetrics


def _health_endpoint(app):
    route = next(route for route in app.routes if getattr(route, "path", None) == "/health")
    return route.endpoint


def _metrics_endpoint(app):
    route = next(route for route in app.routes if getattr(route, "path", None) == "/metrics")
    return route.endpoint


def test_health_endpoint_returns_report_and_ok_status(tmp_path):
    app = create_health_app(HealthMonitor(TradeRepository(tmp_path / "trades.sqlite3")))
    response = Response()

    payload = _health_endpoint(app)(response)

    assert response.status_code == 200
    assert payload["healthy"] is True
    assert payload["checks"]["database"]["ok"] is True


def test_health_endpoint_returns_service_unavailable_on_failure(tmp_path):
    def failing_probe():
        raise ConnectionError("redis unavailable")

    app = create_health_app(
        HealthMonitor(TradeRepository(tmp_path / "trades.sqlite3"), failing_probe)
    )
    response = Response()

    payload = _health_endpoint(app)(response)

    assert response.status_code == 503
    assert payload["healthy"] is False
    assert "redis unavailable" in payload["checks"]["queue"]["detail"]


def test_metrics_endpoint_returns_runtime_counters(tmp_path):
    metrics = RuntimeMetrics(cycles=3, signals=4, errors=1)
    app = create_health_app(
        HealthMonitor(TradeRepository(tmp_path / "trades.sqlite3")), metrics
    )

    payload = _metrics_endpoint(app)()

    assert payload["cycles"] == 3
    assert payload["signals"] == 4
    assert payload["errors"] == 1


def test_metrics_endpoint_returns_zeroes_without_runtime_metrics(tmp_path):
    app = create_health_app(HealthMonitor(TradeRepository(tmp_path / "trades.sqlite3")))

    payload = _metrics_endpoint(app)()

    assert payload["cycles"] == 0
