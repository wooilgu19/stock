"""Small LSTM classifier for the BUY/SELL/HOLD signal strategy.

Deliberately small (default hidden_size=16, 1 layer): the training data
available as of 2026-09-20 is a few thousand real ticks, nowhere near enough
to justify a larger network -- see the design spec's "알려진 한계" section.
Retrain with a larger hidden_size once weeks of recorded data have
accumulated.
"""

import torch
from torch import nn


class LSTMClassifier(nn.Module):
    def __init__(self, input_size: int = 2, hidden_size: int = 16, num_layers: int = 1,
                 num_classes: int = 3, dropout: float = 0.2) -> None:
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_size, hidden_size=hidden_size, num_layers=num_layers,
            batch_first=True, dropout=dropout if num_layers > 1 else 0.0,
        )
        self.dropout = nn.Dropout(dropout)
        self.classifier = nn.Linear(hidden_size, num_classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        _, (hidden, _) = self.lstm(x)
        last_layer_hidden = hidden[-1]  # (batch, hidden_size)
        return self.classifier(self.dropout(last_layer_hidden))
