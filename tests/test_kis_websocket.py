import asyncio
import json
from zoneinfo import ZoneInfo

import pytest
import requests

from src.api.kis_websocket import KISWebSocketClient, KISWebSocketError, _RECORD_FIELD_COUNT


def make_record(symbol="005930", exec_time="101530", price="70000", volume="1234"):
    """Build one 46-field H0STCNT0 record with the fields the client reads set."""
    fields = ["0"] * _RECORD_FIELD_COUNT
    fields[0] = symbol
    fields[1] = exec_time
    fields[2] = price
    fields[12] = volume
    return fields


def make_frame(*records):
    body = "|".join(field for record in records for field in record)
    return f"0|H0STCNT0|{len(records):03d}|{body}"


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
    with pytest.raises(ValueError, match="6-digit"):
        KISWebSocketClient.subscription_message("approval", "ABC")


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

    connections = iter([OSError("disconnected"), FakeSocket([make_frame(make_record())])])

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
    tick = KISWebSocketClient.parse_message(make_frame(make_record()))
    assert tick.symbol == "005930"
    assert tick.price == 70000
    assert tick.volume == 1234


def test_multi_record_frame_yields_one_tick_per_record():
    frame = make_frame(
        make_record(symbol="005930", price="70000", volume="10"),
        make_record(symbol="000660", price="123000", volume="5"),
    )
    ticks = KISWebSocketClient.parse_ticks(frame)
    assert [t.symbol for t in ticks] == ["005930", "000660"]
    assert [t.volume for t in ticks] == [10, 5]


def test_execution_time_field_is_used_for_tick_timestamp():
    tick = KISWebSocketClient.parse_message(make_frame(make_record(exec_time="093015")))
    kst = tick.timestamp.astimezone(ZoneInfo("Asia/Seoul"))
    assert (kst.hour, kst.minute, kst.second) == (9, 30, 15)


def test_invalid_payload_is_rejected():
    with pytest.raises(KISWebSocketError):
        KISWebSocketClient.parse_message("0|H0STCNT0|001|005930|bad")


def test_single_record_frame_with_trailing_fields_trimmed_is_still_parsed():
    """KIS's live gateway drops trailing empty optional fields on the wire,
    so a real single-record frame can be shorter than the documented 46
    fields -- as long as the fields this client reads (indices 0-12) are
    present. This is what actually arrived at 2026-09-07 market open and
    crashed the collector before this fix.
    """
    record = make_record()[:13]  # only the fields the client reads
    frame = f"0|H0STCNT0|001|{'|'.join(record)}"
    tick = KISWebSocketClient.parse_message(frame)
    assert tick.symbol == "005930"
    assert tick.price == 70000
    assert tick.volume == 1234


def test_multi_record_frame_still_rejects_genuinely_truncated_payload():
    """The trimmed-trailing-fields tolerance only covers what a real KIS
    frame can legitimately look like (down to 13 fields on the last
    record); a frame far shorter than that is still a real error.
    """
    frame = "0|H0STCNT0|002|" + "|".join(make_record()[:5])
    with pytest.raises(KISWebSocketError):
        KISWebSocketClient.parse_ticks(frame)


def test_json_ack_is_ignored():
    assert KISWebSocketClient.parse_message('{"header":{"tr_id":"H0STCNT0"}}') is None
