from datetime import datetime, timedelta, timezone

import pytest

from src.api.kis_rest import AccessToken, KISAPIError, KISRestClient


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
