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
    }


def test_metrics_reject_negative_signal_count():
    with pytest.raises(ValueError, match="signals"):
        RuntimeMetrics().record(-1)
