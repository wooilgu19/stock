from datetime import datetime, timezone
from pathlib import Path

import pytest
import torch

from src.models import SignalAction, Tick
from src.strategies.lstm_strategy import LSTMStrategy
from src.training.model import LSTMClassifier

_TS = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _write_checkpoint(path: Path, window_size=4, hidden_size=4, num_layers=1) -> None:
    model = LSTMClassifier(input_size=2, hidden_size=hidden_size, num_layers=num_layers,
                            num_classes=3)
    torch.save({
        "state_dict": model.state_dict(),
        "window_size": window_size,
        "lookahead": 2,
        "low_threshold": -0.01,
        "high_threshold": 0.01,
        "hidden_size": hidden_size,
        "num_layers": num_layers,
    }, path)


def test_holds_until_window_buffer_is_full(tmp_path):
    checkpoint_path = tmp_path / "model.pt"
    _write_checkpoint(checkpoint_path, window_size=4)
    strategy = LSTMStrategy(model_path=checkpoint_path)

    for price in (100.0, 100.5, 101.0):  # only 3 of 4 needed to fill the buffer
        signal = strategy.on_tick(Tick(symbol="005930", price=price, volume=10, timestamp=_TS))
        assert signal.action == SignalAction.HOLD
        assert signal.strength == 0.0


def test_emits_a_valid_signal_once_buffer_is_full(tmp_path):
    checkpoint_path = tmp_path / "model.pt"
    _write_checkpoint(checkpoint_path, window_size=4)
    strategy = LSTMStrategy(model_path=checkpoint_path)

    signal = None
    for price in (100.0, 100.5, 101.0, 101.5):
        signal = strategy.on_tick(Tick(symbol="005930", price=price, volume=10, timestamp=_TS))

    assert signal.action in (SignalAction.BUY, SignalAction.SELL, SignalAction.HOLD)
    assert 0.0 <= signal.strength <= 1.0
    assert signal.symbol == "005930"
    assert signal.strategy_id == "lstm"


def test_missing_checkpoint_raises_immediately(tmp_path):
    with pytest.raises(FileNotFoundError):
        LSTMStrategy(model_path=tmp_path / "does-not-exist.pt")


def test_buffers_are_kept_independently_per_symbol(tmp_path):
    checkpoint_path = tmp_path / "model.pt"
    _write_checkpoint(checkpoint_path, window_size=4)
    strategy = LSTMStrategy(model_path=checkpoint_path)

    for price in (100.0, 100.5, 101.0):
        strategy.on_tick(Tick(symbol="005930", price=price, volume=10, timestamp=_TS))
    # 000660's buffer must still be empty -- this must HOLD, not reuse 005930's buffer
    signal = strategy.on_tick(Tick(symbol="000660", price=50000.0, volume=5, timestamp=_TS))

    assert signal.action == SignalAction.HOLD
