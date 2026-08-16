"""HTTP readiness endpoint for local dependencies."""

from fastapi import FastAPI, Response

from src.monitoring.health import HealthMonitor


def create_health_app(monitor: HealthMonitor) -> FastAPI:
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

    return app
