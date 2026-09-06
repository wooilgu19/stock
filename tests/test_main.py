import asyncio
import json
import threading

import pytest

from src.engine.order_manager import OrderResult
from src.main import _log_signal_result, _run_collector, _run_status_logger, build_parser, main
from src.models import Signal, SignalAction
from src.monitoring.metrics import RuntimeMetrics


def test_build_parser_defaults():
    args = build_parser().parse_args(["005930", "000660"])
    assert args.symbols == ["005930", "000660"]
    assert args.quantity == 1
    assert args.poll_interval == 1.0
    assert args.health_port is None
    assert args.status_interval == 10.0


def test_log_signal_result_ignores_hold_signals(caplog):
    _log_signal_result(
        Signal("005930", SignalAction.HOLD, 0.0, 70_000, "baseline"), None,
    )
    assert "005930" not in caplog.text


def test_log_signal_result_logs_accepted_and_rejected_orders(caplog):
    buy = Signal("005930", SignalAction.BUY, 0.8, 70_000, "baseline")
    with caplog.at_level("INFO"):
        _log_signal_result(buy, OrderResult(True, order_id="trade-1"))
        _log_signal_result(buy, OrderResult(False, reason="market is closed"))
    assert "accepted" in caplog.text and "trade-1" in caplog.text
    assert "rejected" in caplog.text and "market is closed" in caplog.text


def test_status_logger_stops_when_stop_event_is_set(caplog):
    metrics = RuntimeMetrics()
    metrics.record(signals=2)
    stop_event = threading.Event()

    thread = threading.Thread(target=_run_status_logger, args=(metrics, stop_event, 0.02))
    with caplog.at_level("INFO"):
        thread.start()
        stop_event.wait(0.06)  # let at least one snapshot fire
        stop_event.set()
        thread.join(timeout=2)

    assert not thread.is_alive()
    assert "signals=2" in caplog.text


class ForeverStreamClient:
    def __init__(self, *args, **kwargs):
        pass

    async def stream_to_queue(self, symbols, queue):
        await asyncio.Event().wait()


class FailingStreamClient:
    def __init__(self, *args, **kwargs):
        pass

    async def stream_to_queue(self, symbols, queue):
        raise RuntimeError("reconnect limit exceeded")


def test_run_collector_stops_promptly_when_stop_event_is_set(monkeypatch):
    monkeypatch.setattr("src.main.KISWebSocketClient", ForeverStreamClient)
    stop_event = threading.Event()

    async def scenario():
        collector = asyncio.ensure_future(
            _run_collector(FakeSettings(), ["005930"], queue=None, stop_event=stop_event)
        )
        await asyncio.sleep(0.05)
        stop_event.set()
        await asyncio.wait_for(collector, timeout=2)

    asyncio.run(scenario())


def test_run_collector_stops_the_shared_stop_event_when_collector_fails(monkeypatch):
    # The trading loop reads from the same Redis stream the collector
    # publishes to; if the collector dies, the trading loop must be told to
    # stop too instead of polling a stream nothing is feeding forever.
    monkeypatch.setattr("src.main.KISWebSocketClient", FailingStreamClient)
    stop_event = threading.Event()

    asyncio.run(_run_collector(FakeSettings(), ["005930"], queue=None, stop_event=stop_event))

    assert stop_event.is_set()


class FakeSettings:
    kis_appkey = "key"
    kis_appsecret = "secret"
    kis_base_url = "https://example.invalid"
    is_paper = True


def test_build_parser_accepts_record_and_replay_flags():
    args = build_parser().parse_args(["005930", "--record", "ticks.jsonl"])
    assert args.record == "ticks.jsonl"
    assert args.replay is None

    args = build_parser().parse_args(["005930", "--replay", "ticks.jsonl"])
    assert args.replay == "ticks.jsonl"
    assert args.record is None


def test_main_rejects_record_and_replay_together(tmp_path, monkeypatch):
    monkeypatch.setenv("KIS_APPKEY", "key")
    monkeypatch.setenv("KIS_APPSECRET", "secret")
    monkeypatch.setenv("PAPER_TRADING", "true")

    with pytest.raises(SystemExit, match="not both"):
        main(["005930", "--record", "a.jsonl", "--replay", "b.jsonl"])


def test_main_replay_mode_runs_without_kis_credentials(tmp_path, monkeypatch):
    replay_path = tmp_path / "ticks.jsonl"
    replay_path.write_text(
        json.dumps({"ts": 1.0, "payload": {
            "symbol": "005930", "price": 70000, "volume": 10,
        }}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("KIS_APPKEY", "")
    monkeypatch.setenv("KIS_APPSECRET", "")
    monkeypatch.setenv("PAPER_TRADING", "true")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "trades.sqlite3"))

    class FakeQueue:
        def __init__(self, *args, **kwargs):
            pass

        def publish(self, message):
            return "1-0"

        def read(self, last_id="0-0", count=10):
            return []

    monkeypatch.setattr("src.main.RedisQueue", FakeQueue)

    result = main(["005930", "--replay", str(replay_path), "--status-interval", "0"])

    assert result == 0
