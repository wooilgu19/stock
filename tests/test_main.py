import asyncio
import threading

from src.main import _run_collector, build_parser


def test_build_parser_defaults():
    args = build_parser().parse_args(["005930", "000660"])
    assert args.symbols == ["005930", "000660"]
    assert args.quantity == 1
    assert args.poll_interval == 1.0
    assert args.health_port is None


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
