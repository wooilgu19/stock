import asyncio
import json

import pytest
import requests

from src.api.kis_websocket import KISWebSocketClient, KISWebSocketError


class FakeHTTPResponse:
    def __init__(self, body, status_code=200):
        self.body = body
        self.status_code = status_code
        self.ok = status_code < 400

    def json(self):
        return self.body


class FakeHTTPSession:
    def __init__(self, response):
        self.response = response

    def post(self, *args, **kwargs):
        return self.response


def test_subscription_message_has_kis_contract():
    message = json.loads(KISWebSocketClient.subscription_message("approval", "005930"))
    assert message["header"]["approval_key"] == "approval"
    assert message["body"]["input"] == {"tr_id": "H0STCNT0", "tr_key": "005930"}


def test_subscription_message_requires_approval_key():
    with pytest.raises(ValueError, match="approval_key"):
        KISWebSocketClient.subscription_message("", "005930")


def test_approval_key_is_parsed_and_transport_errors_are_wrapped():
    client = KISWebSocketClient(
        "key", "secret", http_session=FakeHTTPSession(
            FakeHTTPResponse({"approval_key": "approval"})
        )
    )
    assert client.approval_key() == "approval"

    class FailingSession:
        def post(self, *args, **kwargs):
            raise requests.Timeout("approval timeout")

    failing = KISWebSocketClient("key", "secret", http_session=FailingSession())
    with pytest.raises(KISWebSocketError, match="approval timeout"):
        failing.approval_key()


def test_approval_key_rejects_non_object_response():
    client = KISWebSocketClient(
        "key", "secret", http_session=FakeHTTPSession(FakeHTTPResponse([]))
    )

    with pytest.raises(KISWebSocketError, match="not an object"):
        client.approval_key()


def test_websocket_reconnect_options_are_validated():
    with pytest.raises(ValueError, match="max_reconnects"):
        KISWebSocketClient("key", "secret", max_reconnects=-1)
    with pytest.raises(ValueError, match="reconnect_delay"):
        KISWebSocketClient("key", "secret", reconnect_delay=-1)


def test_websocket_reconnects_after_connection_failure(monkeypatch):
    class FakeSocket:
        def __init__(self, messages=()):
            self.messages = list(messages)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def send(self, message):
            return None

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self.messages:
                return self.messages.pop(0)
            raise StopAsyncIteration

    connections = iter([OSError("disconnected"), FakeSocket([
        "0|H0STCNT0|001|005930|101530|70000|2|100|0.1|70000|69000|71000|68000|70010|69990|1234"
    ])])

    def connect(*args, **kwargs):
        connection = next(connections)
        if isinstance(connection, Exception):
            raise connection
        return connection

    monkeypatch.setattr("src.api.kis_websocket.websockets.connect", connect)
    client = KISWebSocketClient(
        "key", "secret", max_reconnects=1, reconnect_delay=0,
        http_session=FakeHTTPSession(FakeHTTPResponse({"approval_key": "approval"})),
    )

    async def collect_one():
        stream = client.stream(["005930"])
        return await stream.__anext__()

    tick = asyncio.run(collect_one())

    assert tick.symbol == "005930"


def test_pipe_message_is_converted_to_tick():
    fields = ["005930", "101530", "70000", "2", "100", "0.1", "70000", "69000", "71000", "68000", "70010", "69990", "1234"]
    tick = KISWebSocketClient.parse_message("0|H0STCNT0|001|" + "|".join(fields))
    assert tick.symbol == "005930"
    assert tick.price == 70000
    assert tick.volume == 1234


def test_invalid_payload_is_rejected():
    with pytest.raises(KISWebSocketError):
        KISWebSocketClient.parse_message("0|H0STCNT0|001|005930|bad")


def test_json_ack_is_ignored():
    assert KISWebSocketClient.parse_message('{"header":{"tr_id":"H0STCNT0"}}') is None
