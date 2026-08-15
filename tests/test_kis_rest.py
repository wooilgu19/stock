from datetime import datetime, timedelta, timezone

import pytest

from src.api.kis_rest import AccessToken, KISAPIError, KISOrderExecutor, KISRestClient
from src.models import OrderRequest, Side


class FakeResponse:
    def __init__(self, body, status_code=200):
        self.body = body
        self.status_code = status_code
        self.ok = status_code < 400

    def json(self):
        return self.body


class FakeSession:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return next(self.responses)


def test_access_token_is_cached_and_price_is_parsed():
    session = FakeSession([
        FakeResponse({"rt_cd": "0", "access_token": "token", "expires_in": 3600}),
        FakeResponse({"rt_cd": "0", "output": {"stck_prpr": "70000"}}),
    ])
    client = KISRestClient("https://example.test", "key", "secret", session=session)

    assert client.current_price("005930") == 70000
    assert client.access_token() == "token"
    assert len(session.calls) == 2


def test_api_error_is_exposed():
    session = FakeSession([FakeResponse({"rt_cd": "1", "msg1": "bad credentials"})])
    client = KISRestClient("https://example.test", "key", "secret", session=session)
    with pytest.raises(KISAPIError, match="bad credentials"):
        client.access_token()


def test_expiring_token_is_invalid():
    token = AccessToken("value", datetime.now(timezone.utc) + timedelta(seconds=30))
    assert not token.is_valid()


def test_kis_order_executor_submits_limit_order_and_returns_order_number():
    session = FakeSession([
        FakeResponse({"rt_cd": "0", "access_token": "token", "expires_in": 3600}),
        FakeResponse({"rt_cd": "0", "output": {"ODNO": "12345"}}),
    ])
    client = KISRestClient("https://example.test", "key", "secret", session=session)
    executor = KISOrderExecutor(client, "12345678", paper_trading=True)
    order = OrderRequest("005930", Side.BUY, 2, 70000, "baseline", 0.8)

    assert executor.submit(order) == "12345"
    method, url, kwargs = session.calls[1]
    assert method == "POST"
    assert url.endswith("/uapi/domestic-stock/v1/trading/order-cash")
    assert kwargs["headers"]["tr_id"] == "VTTC0802U"
    assert kwargs["json"]["ORD_DVSN"] == "00"
    assert kwargs["json"]["ORD_QTY"] == "2"
    assert kwargs["json"]["ORD_UNPR"] == "70000"


def test_kis_order_executor_rejects_response_without_order_number():
    session = FakeSession([
        FakeResponse({"rt_cd": "0", "access_token": "token", "expires_in": 3600}),
        FakeResponse({"rt_cd": "0", "output": {}}),
    ])
    executor = KISOrderExecutor(
        KISRestClient("https://example.test", "key", "secret", session=session),
        "12345678",
    )
    order = OrderRequest("005930", Side.SELL, 1, 70000, "baseline", 0.8)

    with pytest.raises(KISAPIError, match="ODNO"):
        executor.submit(order)
