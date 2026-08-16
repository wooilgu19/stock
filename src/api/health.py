"""HTTP readiness endpoint for local dependencies."""

from fastapi import FastAPI, Response

from src.monitoring.health import HealthMonitor
from src.monitoring.metrics import RuntimeMetrics


def create_health_app(monitor: HealthMonitor,
                      metrics: RuntimeMetrics | None = None) -> FastAPI:
    """Create a small FastAPI app exposing dependency readiness.

    The endpoint returns HTTP 503 when any configured dependency is down while
    preserving the detailed check payload for operators and probes.
    """
    app = FastAPI(title="Stock Trading Health", docs_url=None, redoc_url=None)

    @app.get("/health")
    def health(response: Response) -> dict:
        report = monitor.check()
        if not report.healthy:
            response.status_code = 503
        return report.as_dict()

    @app.get("/metrics")
    def metrics_endpoint() -> dict:
        return metrics.as_dict() if metrics is not None else RuntimeMetrics().as_dict()

    return app
