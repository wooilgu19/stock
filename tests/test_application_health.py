from src.application import build_health_app
from src.config import Settings


class FakeQueue:
    def __init__(self):
        self.pings = 0

    def ping(self):
        self.pings += 1


def test_build_health_app_uses_configured_dependencies_without_startup_probe(tmp_path):
    queue = FakeQueue()
    settings = Settings(
        database_path=tmp_path / "trades.sqlite3",
        redis_host="redis.example",
        redis_port=6380,
    )

    app = build_health_app(settings, queue=queue)

    assert app.title == "Stock Trading Health"
    assert queue.pings == 0
