import pytest
import requests

from src.monitoring.notifications import NotificationError, TelegramNotifier


class FakeResponse:
    def __init__(self, body, status_code=200):
        self.body = body
        self.status_code = status_code
        self.ok = status_code < 400

    def json(self):
        return self.body


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def test_telegram_notifier_posts_message():
    session = FakeSession(FakeResponse({"ok": True}))
    notifier = TelegramNotifier("token", "chat", session=session)

    notifier("worker failed")

    assert session.calls[0][0].endswith("/bottoken/sendMessage")
    assert session.calls[0][1]["json"] == {"chat_id": "chat", "text": "worker failed"}


def test_telegram_notifier_rejects_api_failure():
    notifier = TelegramNotifier("token", "chat", session=FakeSession(FakeResponse({"ok": False})))

    with pytest.raises(NotificationError, match="rejected"):
        notifier("worker failed")


def test_telegram_notifier_wraps_transport_error():
    class FailingSession:
        def post(self, *args, **kwargs):
            raise requests.Timeout("telegram timeout")

    notifier = TelegramNotifier("token", "chat", session=FailingSession())

    with pytest.raises(NotificationError, match="telegram timeout"):
        notifier("worker failed")
