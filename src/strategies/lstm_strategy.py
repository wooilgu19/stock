"""LSTM-based SignalPredictor, trained offline by src/training/train.py.

Implements the same on_tick(tick) -> Signal shape as MovingAverageStrategy
(see src/inference/worker.py's SignalPredictor protocol), so it drops into
the existing pipeline (risk gate, order manager, --replay) unchanged.
"""

from collections import defaultdict, deque
from pathlib import Path

import torch

from src.models import Signal, SignalAction, Tick
from src.training.model import LSTMClassifier
from src.training.windowing import LABEL_BUY, LABEL_HOLD, LABEL_SELL, normalize_window

_LABEL_TO_ACTION = {
    LABEL_BUY: SignalAction.BUY,
    LABEL_SELL: SignalAction.SELL,
    LABEL_HOLD: SignalAction.HOLD,
}


class LSTMStrategy:
    def __init__(self, model_path: str | Path = "models/lstm_v1.pt",
                 strategy_id: str = "lstm") -> None:
        model_path = Path(model_path)
        if not model_path.exists():
            raise FileNotFoundError(f"LSTM checkpoint not found: {model_path}")

        checkpoint = torch.load(model_path, map_location="cpu")
        self.window_size = checkpoint["window_size"]
        self.strategy_id = strategy_id

        self.model = LSTMClassifier(
            input_size=2, hidden_size=checkpoint["hidden_size"],
            num_layers=checkpoint["num_layers"], num_classes=3,
        )
        self.model.load_state_dict(checkpoint["state_dict"])
        self.model.eval()

        self._prices: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=self.window_size)
        )
        self._volumes: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=self.window_size)
        )

    def on_tick(self, tick: Tick) -> Signal:
        prices = self._prices[tick.symbol]
        volumes = self._volumes[tick.symbol]
        prices.append(tick.price)
        volumes.append(tick.volume)

        if len(prices) < self.window_size:
            return Signal(tick.symbol, SignalAction.HOLD, 0.0, tick.price,
                          self.strategy_id, tick.timestamp)

        features = normalize_window(list(prices), list(volumes))
        batch = torch.tensor([features], dtype=torch.float32)
        with torch.no_grad():
            probabilities = torch.softmax(self.model(batch)[0], dim=-1)
        label = int(torch.argmax(probabilities))
        strength = float(probabilities[label])
        action = _LABEL_TO_ACTION[label]

        return Signal(tick.symbol, action, strength if action != SignalAction.HOLD else 0.0,
                      tick.price, self.strategy_id, tick.timestamp)
