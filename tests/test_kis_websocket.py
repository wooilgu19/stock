import json

import pytest

from src.api.kis_websocket import KISWebSocketClient, KISWebSocketError


def test_subscription_message_has_kis_contract():
    message = json.loads(KISWebSocketClient.subscription_message("approval", "005930"))
    assert message["header"]["approval_key"] == "approval"
    assert message["body"]["input"] == {"tr_id": "H0STCNT0", "tr_key": "005930"}


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
