import pytest

from src.monitoring.metrics import RuntimeMetrics


def test_metrics_accumulate_errors_and_reconciliation_counts():
    metrics = RuntimeMetrics()

    metrics.record(2, ("worker: failed",), type("Result", (), {
        "updated": 3, "ignored": 1,
    })())

    assert metrics.as_dict() == {
        "cycles": 1,
        "signals": 2,
        "errors": 1,
        "reconciliation_updates": 3,
        "reconciliation_ignored": 1,
        "last_error": "worker: failed",
        "last_tick_at": None,
    }


def test_metrics_track_last_tick_and_lag():
    from datetime import datetime, timedelta, timezone

    metrics = RuntimeMetrics()
    now = datetime(2026, 11, 4, 1, 0, tzinfo=timezone.utc)
    assert metrics.lag_seconds(now) is None

    metrics.record(5, last_tick_at=now - timedelta(seconds=90))
    metrics.record(0)  # an empty cycle keeps the previous tick time

    assert metrics.lag_seconds(now) == 90
    assert metrics.as_dict()["last_tick_at"] == "2026-11-04T00:58:30+00:00"


def test_metrics_reject_negative_signal_count():
    with pytest.raises(ValueError, match="signals"):
        RuntimeMetrics().record(-1)
