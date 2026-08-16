"""Queue consumer that converts market ticks into trading signals."""

from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol

from src.models import Signal, Tick


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
                 on_signal: Callable[[Signal], None] | None = None,
                 cursor_store: Any = None, cursor_name: str = "stock:ticks",
                 on_error: Callable[[str], None] | None = None) -> None:
        self.queue = queue
        self.predictor = predictor
        self.on_signal = on_signal
        self.cursor_store = cursor_store
        self.cursor_name = cursor_name
        self.on_error = on_error
        self.last_id = (cursor_store.stream_cursor(cursor_name)
                        if cursor_store is not None else "0-0")

    def process_once(self, count: int = 10) -> list[Signal]:
        if count <= 0:
            raise ValueError("count must be positive")
        signals: list[Signal] = []
        try:
            for message_id, payload in self.queue.read(self.last_id, count):
                try:
                    signal = self.predictor.on_tick(tick_from_message(payload))
                    if self.on_signal:
                        self.on_signal(signal)
                except ValueError as exc:
                    # Malformed/poison input cannot succeed on retry. Consume
                    # it and report it, while broker/network errors below
                    # remain retryable (last_id is left unadvanced for them).
                    if self.on_error:
                        self.on_error(f"message {message_id}: {exc}")
                    self.last_id = message_id
                    continue
                # Commit only after downstream order handling succeeds. A
                # failed callback is retried instead of silently losing the
                # tick, and it also stops this batch's cursor from advancing
                # past it (see finally below).
                self.last_id = message_id
                signals.append(signal)
        finally:
            # Persisting once per batch instead of once per message trades a
            # bounded amount of re-processing after a crash mid-batch (safe,
            # since order submission is idempotent on client_order_id) for
            # avoiding a disk fsync on every single tick.
            if self.cursor_store is not None:
                self.cursor_store.save_stream_cursor(self.cursor_name, self.last_id)
        return signals
