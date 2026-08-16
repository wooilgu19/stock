"""Dependency health checks suitable for a lightweight readiness endpoint."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from src.database.sqlite import TradeRepository


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    detail: str = "ok"

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "detail": self.detail}


@dataclass(frozen=True)
class HealthReport:
    healthy: bool
    checks: dict[str, CheckResult]
    checked_at: datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "healthy": self.healthy,
            "checked_at": self.checked_at.isoformat(),
            "checks": {name: result.as_dict() for name, result in self.checks.items()},
        }


class HealthMonitor:
    """Run non-mutating checks against the configured local dependencies."""

    def __init__(self, repository: TradeRepository,
                 queue_probe: Callable[[], None] | None = None) -> None:
        self.repository = repository
        self.queue_probe = queue_probe

    def check(self) -> HealthReport:
        checks: dict[str, CheckResult] = {
            "database": self._run(self.repository.ping),
        }
        if self.queue_probe is not None:
            checks["queue"] = self._run(self.queue_probe)
        return HealthReport(
            healthy=all(result.ok for result in checks.values()),
            checks=checks,
            checked_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _run(probe: Callable[[], None]) -> CheckResult:
        try:
            probe()
        except Exception as exc:  # health checks must report failures, not hide them
            return CheckResult(False, f"{type(exc).__name__}: {exc}")
        return CheckResult(True)
