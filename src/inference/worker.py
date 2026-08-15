"""Queue consumer that converts market ticks into trading signals."""

from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol

from src.models import Signal, SignalAction, Tick


class TickQueue(Protocol):
    def read(self, last_id: str = "0-0", count: int = 10) -> list[tuple[str, dict[str, Any]]]: ...


class SignalPredictor(Protocol):
    def on_tick(self, tick: Tick) -> Signal: ...


def tick_from_message(message: dict[str, Any]) -> Tick:
    try:
        timestamp = message.get("timestamp")
        parsed_timestamp = datetime.fromisoformat(timestamp) if timestamp else None
        return Tick(symbol=str(message["symbol"]), price=float(message["price"]),
                    volume=int(message["volume"]), timestamp=parsed_timestamp or datetime.now().astimezone())
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("invalid tick queue message") from exc


class InferenceWorker:
    def __init__(self, queue: TickQueue, predictor: SignalPredictor,
                 on_signal: Callable[[Signal], None] | None = None) -> None:
        self.queue = queue
        self.predictor = predictor
        self.on_signal = on_signal
        self.last_id = "0-0"

    def process_once(self, count: int = 10) -> list[Signal]:
        signals: list[Signal] = []
        for message_id, payload in self.queue.read(self.last_id, count):
            signal = self.predictor.on_tick(tick_from_message(payload))
            self.last_id = message_id
            signals.append(signal)
            if self.on_signal:
                self.on_signal(signal)
        return signals
