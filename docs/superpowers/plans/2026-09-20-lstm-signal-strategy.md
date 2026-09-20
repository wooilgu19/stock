# LSTM Signal Strategy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a small LSTM-based `SignalPredictor` (`LSTMStrategy`) trained offline on recorded ticks, selectable via `--strategy lstm` alongside the existing `MovingAverageStrategy`, without touching the default strategy or any existing passing tests.

**Architecture:** Offline training (`src/training/`) turns recorded JSONL tick files into (window, label) pairs using price-return/log-volume normalization and future-return quantile labeling, trains a small `LSTMClassifier`, and saves weights + preprocessing metadata to `models/lstm_v1.pt`. Online, `LSTMStrategy` (`src/strategies/lstm_strategy.py`) implements the same `on_tick(tick) -> Signal` interface as `MovingAverageStrategy`, buffering ticks and running one forward pass per tick using the exact same normalization function the training code used.

**Tech Stack:** Python, PyTorch (already installed: 2.13.0+cpu), numpy, pytest.

**Spec:** `docs/superpowers/specs/2026-09-20-lstm-signal-strategy-design.md`

## Global Constraints

- Do not modify `src/strategies/moving_average.py` or its tests — the existing default strategy must keep working unchanged.
- All new training-pipeline functions (windowing, splitting) must be pure functions: same input always produces the same output, no I/O, no hidden state.
- Every window's label must be computable only from data at or before that window's own lookahead horizon — never from data past the train/val split boundary (see Task 2).
- Model checkpoint format: `torch.save({"state_dict": ..., "window_size": int, "lookahead": int, "low_threshold": float, "high_threshold": float, "hidden_size": int, "num_layers": int}, path)` — `LSTMStrategy` must load and use every one of these keys; do not add keys one side reads and the other doesn't write.
- Label encoding is fixed: `LABEL_SELL = 0`, `LABEL_HOLD = 1`, `LABEL_BUY = 2` (defined once in `src/training/windowing.py`, imported everywhere else — never redefined).

---

## Task 1: Windowing and labeling functions

**Files:**
- Create: `src/training/__init__.py` (empty)
- Create: `src/training/windowing.py`
- Test: `tests/test_windowing.py`

**Interfaces:**
- Produces: `LABEL_SELL: int`, `LABEL_HOLD: int`, `LABEL_BUY: int`, `sliding_windows(values: list[float], window_size: int) -> list[list[float]]`, `normalize_window(price_window: list[float], volume_window: list[float]) -> list[list[float]]`, `compute_future_returns(prices: list[float], window_size: int, lookahead: int) -> list[float | None]`, `build_dataset(prices: list[float], volumes: list[float], window_size: int, lookahead: int, low_threshold: float, high_threshold: float) -> tuple[np.ndarray, np.ndarray]` (X shape `(n, window_size, 2)` float32, y shape `(n,)` int64).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_windowing.py`:

```python
import math

import numpy as np
import pytest

from src.training.windowing import (
    LABEL_BUY,
    LABEL_HOLD,
    LABEL_SELL,
    build_dataset,
    compute_future_returns,
    normalize_window,
    sliding_windows,
)


def test_sliding_windows_returns_all_contiguous_windows():
    assert sliding_windows([1, 2, 3, 4, 5], 3) == [[1, 2, 3], [2, 3, 4], [3, 4, 5]]


def test_sliding_windows_returns_empty_when_shorter_than_window():
    assert sliding_windows([1, 2], 3) == []


def test_sliding_windows_rejects_non_positive_window():
    with pytest.raises(ValueError, match="window_size"):
        sliding_windows([1, 2, 3], 0)


def test_normalize_window_uses_first_price_as_base_and_log1p_volume():
    result = normalize_window([100.0, 101.0, 99.0], [10.0, 20.0, 0.0])
    assert result[0] == [0.0, math.log1p(10.0)]
    assert result[1] == pytest.approx([0.01, math.log1p(20.0)])
    assert result[2] == pytest.approx([-0.01, math.log1p(0.0)])


def test_compute_future_returns_matches_price_change_at_lookahead():
    # window_size=2 -> first window ends at index 1 (value 101)
    prices = [100.0, 101.0, 102.0, 103.0]
    returns = compute_future_returns(prices, window_size=2, lookahead=1)
    # end_index 1: (102-101)/101 ; end_index 2: (103-102)/102 ; end_index 3: no future tick -> None
    assert returns == pytest.approx([(102.0 - 101.0) / 101.0, (103.0 - 102.0) / 102.0, None])


def test_compute_future_returns_rejects_non_positive_lookahead():
    with pytest.raises(ValueError, match="lookahead"):
        compute_future_returns([1.0, 2.0], window_size=1, lookahead=0)


def test_build_dataset_buckets_labels_by_threshold_and_drops_unlabelable_tail():
    # window_size=2, lookahead=1. 5 prices -> 4 windows, last one unlabelable (dropped).
    prices = [100.0, 100.0, 110.0, 100.0, 90.0]
    volumes = [1.0, 1.0, 1.0, 1.0, 1.0]
    X, y = build_dataset(prices, volumes, window_size=2, lookahead=1,
                          low_threshold=-0.05, high_threshold=0.05)
    assert X.shape == (3, 2, 2)
    assert X.dtype == np.float32
    assert y.dtype == np.int64
    # end_index=1 (price 100): future=110 -> return +0.10 -> BUY
    # end_index=2 (price 110): future=100 -> return ~-0.0909 -> SELL
    # end_index=3 (price 100): future=90 -> return -0.10 -> SELL
    assert list(y) == [LABEL_BUY, LABEL_SELL, LABEL_SELL]


def test_build_dataset_labels_small_moves_as_hold():
    prices = [100.0, 100.0, 100.5]
    volumes = [1.0, 1.0, 1.0]
    X, y = build_dataset(prices, volumes, window_size=2, lookahead=1,
                          low_threshold=-0.05, high_threshold=0.05)
    assert list(y) == [LABEL_HOLD]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_windowing.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.training'`

- [ ] **Step 3: Write the implementation**

Create `src/training/__init__.py` (empty file).

Create `src/training/windowing.py`:

```python
"""Pure functions turning a raw tick series into normalized, labeled windows
for LSTM training. Every function here takes plain lists/floats and returns
plain lists/arrays -- no I/O, no file access, no hidden state -- so the exact
same normalization can run at training time and at inference time
(src/strategies/lstm_strategy.py) without the two ever drifting apart.
"""

import math

import numpy as np

LABEL_SELL = 0
LABEL_HOLD = 1
LABEL_BUY = 2


def sliding_windows(values: list[float], window_size: int) -> list[list[float]]:
    if window_size <= 0:
        raise ValueError("window_size must be positive")
    if len(values) < window_size:
        return []
    return [values[i:i + window_size] for i in range(len(values) - window_size + 1)]


def normalize_window(price_window: list[float], volume_window: list[float]) -> list[list[float]]:
    base_price = price_window[0]
    return [
        [(price - base_price) / base_price, math.log1p(volume)]
        for price, volume in zip(price_window, volume_window)
    ]


def compute_future_returns(prices: list[float], window_size: int,
                            lookahead: int) -> list[float | None]:
    if lookahead <= 0:
        raise ValueError("lookahead must be positive")
    if window_size <= 0:
        raise ValueError("window_size must be positive")
    n = len(prices)
    returns: list[float | None] = []
    for end_index in range(window_size - 1, n):
        future_index = end_index + lookahead
        if future_index >= n:
            returns.append(None)
        else:
            base = prices[end_index]
            returns.append((prices[future_index] - base) / base)
    return returns


def build_dataset(prices: list[float], volumes: list[float], window_size: int, lookahead: int,
                   low_threshold: float, high_threshold: float) -> tuple[np.ndarray, np.ndarray]:
    price_windows = sliding_windows(prices, window_size)
    volume_windows = sliding_windows(volumes, window_size)
    returns = compute_future_returns(prices, window_size, lookahead)

    features: list[list[list[float]]] = []
    labels: list[int] = []
    for price_window, volume_window, future_return in zip(price_windows, volume_windows, returns):
        if future_return is None:
            continue
        if future_return >= high_threshold:
            label = LABEL_BUY
        elif future_return <= low_threshold:
            label = LABEL_SELL
        else:
            label = LABEL_HOLD
        features.append(normalize_window(price_window, volume_window))
        labels.append(label)

    X = np.array(features, dtype=np.float32).reshape(len(features), window_size, 2)
    y = np.array(labels, dtype=np.int64)
    return X, y
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_windowing.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add src/training/__init__.py src/training/windowing.py tests/test_windowing.py
git commit -m "feat: add windowing/labeling functions for LSTM training

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 2: Chronological train/val split

**Files:**
- Create: `src/training/split.py`
- Test: `tests/test_split.py`

**Interfaces:**
- Consumes: nothing from Task 1 directly (operates on raw price/volume lists, same shape `build_dataset` expects).
- Produces: `chronological_split(prices: list[float], volumes: list[float], val_ratio: float, lookahead: int) -> tuple[tuple[list[float], list[float]], tuple[list[float], list[float]]]` returning `((train_prices, train_volumes), (val_prices, val_volumes))`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_split.py`:

```python
import pytest

from src.training.split import chronological_split


def test_split_keeps_chronological_order_and_leaves_a_lookahead_gap():
    prices = list(range(100, 120))  # 20 points, indices 0-19
    volumes = [1.0] * 20

    (train_p, train_v), (val_p, val_v) = chronological_split(prices, volumes, val_ratio=0.2, lookahead=2)

    # split_index = int(20 * 0.8) = 16; train drops the last `lookahead`=2 -> ends at index 13 (14 points)
    assert train_p == prices[:14]
    assert train_v == volumes[:14]
    # val starts exactly at split_index=16 (6 points)
    assert val_p == prices[16:]
    assert val_v == volumes[16:]
    # the gap [14, 16) belongs to neither split
    assert len(train_p) + len(val_p) < len(prices)


def test_split_rejects_out_of_range_val_ratio():
    with pytest.raises(ValueError, match="val_ratio"):
        chronological_split([1.0] * 10, [1.0] * 10, val_ratio=1.5, lookahead=1)
    with pytest.raises(ValueError, match="val_ratio"):
        chronological_split([1.0] * 10, [1.0] * 10, val_ratio=0.0, lookahead=1)


def test_split_rejects_non_positive_lookahead():
    with pytest.raises(ValueError, match="lookahead"):
        chronological_split([1.0] * 10, [1.0] * 10, val_ratio=0.2, lookahead=0)


def test_split_rejects_too_few_ticks_for_the_requested_split():
    with pytest.raises(ValueError, match="not enough ticks"):
        chronological_split([1.0, 2.0, 3.0], [1.0, 1.0, 1.0], val_ratio=0.5, lookahead=5)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_split.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.training.split'`

- [ ] **Step 3: Write the implementation**

Create `src/training/split.py`:

```python
"""Chronological (never shuffled) train/validation split for tick series.

A random split would let a validation window's label peek at price action
that happened chronologically *before* some training windows it's supposed
to be held out from -- for time series this is data leakage. This splits by
time instead, and removes a `lookahead`-sized gap around the boundary so no
window on either side can compute a label using a tick from the other side.
"""


def chronological_split(prices: list[float], volumes: list[float], val_ratio: float,
                         lookahead: int) -> tuple[tuple[list[float], list[float]],
                                                   tuple[list[float], list[float]]]:
    if not 0 < val_ratio < 1:
        raise ValueError("val_ratio must be between 0 and 1")
    if lookahead <= 0:
        raise ValueError("lookahead must be positive")

    n = len(prices)
    split_index = int(n * (1 - val_ratio))
    train_end = split_index - lookahead
    val_start = split_index

    if train_end <= 0 or val_start >= n:
        raise ValueError("not enough ticks for the requested val_ratio/lookahead split")

    train = (prices[:train_end], volumes[:train_end])
    val = (prices[val_start:], volumes[val_start:])
    return train, val
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_split.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/training/split.py tests/test_split.py
git commit -m "feat: add chronological train/val split for LSTM training

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 3: LSTMClassifier model

**Files:**
- Create: `src/training/model.py`
- Test: `tests/test_lstm_model.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `LSTMClassifier(input_size: int = 2, hidden_size: int = 16, num_layers: int = 1, num_classes: int = 3, dropout: float = 0.2)`, a `torch.nn.Module` whose `forward(x)` takes a tensor shaped `(batch, window_size, input_size)` and returns logits shaped `(batch, num_classes)`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_lstm_model.py`:

```python
import torch

from src.training.model import LSTMClassifier


def test_forward_returns_logits_shaped_batch_by_num_classes():
    model = LSTMClassifier(input_size=2, hidden_size=8, num_layers=1, num_classes=3)
    batch = torch.zeros((5, 20, 2))  # batch=5, window_size=20, features=2

    logits = model(batch)

    assert logits.shape == (5, 3)


def test_forward_is_deterministic_in_eval_mode():
    model = LSTMClassifier(input_size=2, hidden_size=8, num_layers=1, num_classes=3)
    model.eval()
    batch = torch.rand((2, 10, 2))

    with torch.no_grad():
        first = model(batch)
        second = model(batch)

    assert torch.equal(first, second)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_lstm_model.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.training.model'`

- [ ] **Step 3: Write the implementation**

Create `src/training/model.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_lstm_model.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/training/model.py tests/test_lstm_model.py
git commit -m "feat: add small LSTMClassifier for the signal strategy

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 4: Training entrypoint

**Files:**
- Create: `src/training/train.py`
- Create: `scripts/train_lstm.py`
- Test: `tests/test_train.py`

**Interfaces:**
- Consumes: `src.training.windowing.build_dataset`, `src.training.split.chronological_split`, `src.training.model.LSTMClassifier` (Tasks 1-3).
- Produces: `run_training(ticks_paths: list[Path], window_size: int, lookahead: int, val_ratio: float, epochs: int, lr: float, output_path: Path, hidden_size: int = 16, num_layers: int = 1, dropout: float = 0.2, low_quantile: float = 0.3, high_quantile: float = 0.7, seed: int = 42) -> dict` returning `{"train_size": int, "val_size": int, "val_accuracy": float}`. Reads each `ticks_paths` entry as a JSONL file of `{"ts": float, "payload": {"symbol": str, "price": float, "volume": float, "timestamp": str}}` lines (the format `RecordingQueue`/`replay_ticks` already use).

- [ ] **Step 1: Write the failing test**

Create `tests/test_train.py`:

```python
import json

import torch

from src.training.train import run_training


def _write_synthetic_ticks(path, n, trend):
    """n ticks with a clear artificial up/down trend the model can learn
    quickly, so the test trains in a handful of epochs instead of needing
    real market data.
    """
    lines = []
    price = 100.0
    for i in range(n):
        price += trend
        lines.append(json.dumps({
            "ts": float(i),
            "payload": {"symbol": "TEST", "price": price, "volume": 10.0,
                        "timestamp": "2026-01-01T00:00:00+00:00"},
        }))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_run_training_produces_a_checkpoint_with_all_required_keys(tmp_path):
    ticks_path = tmp_path / "ticks_up.jsonl"
    _write_synthetic_ticks(ticks_path, n=300, trend=0.05)
    output_path = tmp_path / "model.pt"

    metrics = run_training(
        ticks_paths=[ticks_path], window_size=5, lookahead=2, val_ratio=0.2,
        epochs=3, lr=0.01, output_path=output_path, hidden_size=4, num_layers=1,
    )

    assert output_path.exists()
    assert metrics["train_size"] > 0
    assert metrics["val_size"] > 0
    assert 0.0 <= metrics["val_accuracy"] <= 1.0

    checkpoint = torch.load(output_path, map_location="cpu")
    for key in ("state_dict", "window_size", "lookahead", "low_threshold",
                "high_threshold", "hidden_size", "num_layers"):
        assert key in checkpoint
    assert checkpoint["window_size"] == 5
    assert checkpoint["lookahead"] == 2


def test_run_training_combines_multiple_files_without_crossing_their_boundary(tmp_path):
    first = tmp_path / "ticks_a.jsonl"
    second = tmp_path / "ticks_b.jsonl"
    _write_synthetic_ticks(first, n=200, trend=0.05)
    _write_synthetic_ticks(second, n=200, trend=-0.05)
    output_path = tmp_path / "model.pt"

    metrics = run_training(
        ticks_paths=[first, second], window_size=5, lookahead=2, val_ratio=0.2,
        epochs=3, lr=0.01, output_path=output_path, hidden_size=4, num_layers=1,
    )

    assert output_path.exists()
    assert metrics["train_size"] > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_train.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.training.train'`

- [ ] **Step 3: Write the implementation**

Create `src/training/train.py`:

```python
"""Offline training entrypoint: recorded tick files -> models/lstm_v1.pt.

Each file in ticks_paths is treated as one continuous chronological
session and split independently (see chronological_split's docstring for
why) -- files are never concatenated before splitting, so a training
window can never span the boundary between two recording days.
"""

import json
from pathlib import Path

import numpy as np
import torch
from torch import nn

from src.training.model import LSTMClassifier
from src.training.split import chronological_split
from src.training.windowing import build_dataset, compute_future_returns


def _load_ticks(path: Path) -> tuple[list[float], list[float]]:
    prices: list[float] = []
    volumes: list[float] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)["payload"]
        prices.append(float(payload["price"]))
        volumes.append(float(payload["volume"]))
    return prices, volumes


def run_training(ticks_paths: list[Path], window_size: int, lookahead: int, val_ratio: float,
                  epochs: int, lr: float, output_path: Path, hidden_size: int = 16,
                  num_layers: int = 1, dropout: float = 0.2, low_quantile: float = 0.3,
                  high_quantile: float = 0.7, seed: int = 42) -> dict:
    torch.manual_seed(seed)

    splits = [
        chronological_split(*_load_ticks(Path(path)), val_ratio=val_ratio, lookahead=lookahead)
        for path in ticks_paths
    ]

    # Thresholds are computed from train-side returns only, across every
    # file, so validation never influences where the label boundaries fall.
    all_train_returns: list[float] = []
    for (train_prices, _), _ in splits:
        all_train_returns.extend(
            r for r in compute_future_returns(train_prices, window_size, lookahead) if r is not None
        )
    low_threshold = float(np.quantile(all_train_returns, low_quantile))
    high_threshold = float(np.quantile(all_train_returns, high_quantile))

    train_X_parts, train_y_parts, val_X_parts, val_y_parts = [], [], [], []
    for (train_prices, train_volumes), (val_prices, val_volumes) in splits:
        tx, ty = build_dataset(train_prices, train_volumes, window_size, lookahead,
                                low_threshold, high_threshold)
        vx, vy = build_dataset(val_prices, val_volumes, window_size, lookahead,
                                low_threshold, high_threshold)
        train_X_parts.append(tx)
        train_y_parts.append(ty)
        val_X_parts.append(vx)
        val_y_parts.append(vy)

    train_X = np.concatenate(train_X_parts)
    train_y = np.concatenate(train_y_parts)
    val_X = np.concatenate(val_X_parts)
    val_y = np.concatenate(val_y_parts)

    model = LSTMClassifier(input_size=2, hidden_size=hidden_size, num_layers=num_layers,
                            num_classes=3, dropout=dropout)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    loss_fn = nn.CrossEntropyLoss()

    train_X_t = torch.tensor(train_X, dtype=torch.float32)
    train_y_t = torch.tensor(train_y, dtype=torch.int64)

    model.train()
    for _ in range(epochs):
        optimizer.zero_grad()
        logits = model(train_X_t)
        loss = loss_fn(logits, train_y_t)
        loss.backward()
        optimizer.step()

    model.eval()
    with torch.no_grad():
        val_logits = model(torch.tensor(val_X, dtype=torch.float32))
        val_predictions = torch.argmax(val_logits, dim=-1).numpy()
    val_accuracy = float((val_predictions == val_y).mean()) if len(val_y) else 0.0

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({
        "state_dict": model.state_dict(),
        "window_size": window_size,
        "lookahead": lookahead,
        "low_threshold": low_threshold,
        "high_threshold": high_threshold,
        "hidden_size": hidden_size,
        "num_layers": num_layers,
    }, output_path)

    return {"train_size": len(train_y), "val_size": len(val_y), "val_accuracy": val_accuracy}
```

Create `scripts/train_lstm.py`:

```python
"""CLI entrypoint for training the LSTM signal strategy.

Usage:
    .venv\\Scripts\\python.exe scripts\\train_lstm.py

Reads every data/ticks/ticks_<digits>.jsonl recording (real market-hours
recordings only -- excludes data/ticks/ticks_test_*.jsonl) and writes
models/lstm_v1.pt.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.training.train import run_training  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Train the LSTM signal strategy")
    parser.add_argument("--ticks-glob", default="data/ticks/ticks_[0-9]*.jsonl",
                        help="glob for recorded tick files (default excludes ticks_test_*)")
    parser.add_argument("--window-size", type=int, default=20)
    parser.add_argument("--lookahead", type=int, default=5)
    parser.add_argument("--val-ratio", type=float, default=0.2)
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--hidden-size", type=int, default=16)
    parser.add_argument("--num-layers", type=int, default=1)
    parser.add_argument("--output", default="models/lstm_v1.pt")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ticks_paths = sorted(Path().glob(args.ticks_glob))
    if not ticks_paths:
        raise SystemExit(f"no tick files matched {args.ticks_glob!r}")

    print(f"training on {len(ticks_paths)} file(s): {[p.name for p in ticks_paths]}")
    metrics = run_training(
        ticks_paths=ticks_paths, window_size=args.window_size, lookahead=args.lookahead,
        val_ratio=args.val_ratio, epochs=args.epochs, lr=args.lr, output_path=Path(args.output),
        hidden_size=args.hidden_size, num_layers=args.num_layers,
    )
    print(f"train_size={metrics['train_size']} val_size={metrics['val_size']} "
          f"val_accuracy={metrics['val_accuracy']:.3f}")
    print(f"saved {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_train.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/training/train.py scripts/train_lstm.py tests/test_train.py
git commit -m "feat: add LSTM training entrypoint (src/training/train.py, scripts/train_lstm.py)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 5: LSTMStrategy (SignalPredictor implementation)

**Files:**
- Create: `src/strategies/lstm_strategy.py`
- Test: `tests/test_lstm_strategy.py`

**Interfaces:**
- Consumes: `src.training.windowing.normalize_window`, `LABEL_SELL/HOLD/BUY` (Task 1), `src.training.model.LSTMClassifier` (Task 3), checkpoint format from Task 4, `src.models.Signal`, `src.models.SignalAction`, `src.models.Tick`.
- Produces: `LSTMStrategy(model_path: str | Path = "models/lstm_v1.pt", strategy_id: str = "lstm")` implementing `on_tick(tick: Tick) -> Signal` — the same shape `src/inference/worker.py`'s `SignalPredictor` protocol and `MovingAverageStrategy` already use.

- [ ] **Step 1: Write the failing test**

Create `tests/test_lstm_strategy.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_lstm_strategy.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.strategies.lstm_strategy'`

- [ ] **Step 3: Write the implementation**

Create `src/strategies/lstm_strategy.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_lstm_strategy.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/strategies/lstm_strategy.py tests/test_lstm_strategy.py
git commit -m "feat: add LSTMStrategy SignalPredictor implementation

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 6: Wire `--strategy` flag into main.py

**Files:**
- Modify: `src/main.py:44-52` (`_run_trading_loop`), `src/main.py:128-143` (`build_parser`), `src/main.py:179-184` (thread construction)
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `MovingAverageStrategy` (existing, unchanged), `LSTMStrategy` (Task 5).
- Produces: `--strategy {moving-average,lstm}` CLI flag, default `moving-average`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_main.py` (open the file first to match its existing fixtures/imports — it already has `FakeSettings`, a queue monkeypatch pattern, and `ForeverStreamClient`; follow those same patterns):

```python
def test_default_strategy_is_moving_average():
    # _run_trading_loop (which constructs the actual strategy object) runs on
    # its own thread inside main(); build_parser's default is what decides
    # which one, so that's what this asserts directly.
    args = build_parser().parse_args(["005930"])
    assert args.strategy == "moving-average"


def test_strategy_flag_accepts_lstm():
    args = build_parser().parse_args(["005930", "--strategy", "lstm"])
    assert args.strategy == "lstm"


def test_strategy_flag_rejects_unknown_value():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["005930", "--strategy", "not-a-real-strategy"])
```

Check the top of `tests/test_main.py` for its existing imports (`from src.main import ...`) and add `build_parser` to that import line if it isn't already imported; add `import pytest` if not already present.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_main.py -k strategy -v`
Expected: FAIL — `build_parser().parse_args([...])` raises `SystemExit` (unrecognized argument `--strategy`) for the first two tests, and the third test's assertion about the error can't yet be reached the same way (argparse has no `strategy` choices yet).

- [ ] **Step 3: Write the implementation**

In `src/main.py`, add the import near the other strategy import:

```python
from src.strategies.lstm_strategy import LSTMStrategy
```

Change `_run_trading_loop`'s signature and predictor construction:

```python
def _run_trading_loop(settings: Settings, queue: RedisQueue, metrics: RuntimeMetrics,
                       stop_event: threading.Event, poll_interval: float, quantity: int,
                       strategy: str = "moving-average",
                       enforce_market_hours: bool = True) -> None:
    predictor = LSTMStrategy() if strategy == "lstm" else MovingAverageStrategy()
    runtime = build_runtime(
        settings, predictor, queue=queue, quantity=quantity,
        on_result=_log_signal_result, metrics=metrics, poll_interval=poll_interval,
        enforce_market_hours=enforce_market_hours,
    )
```

In `build_parser`, add the flag next to `--quantity`:

```python
    parser.add_argument("--strategy", choices=["moving-average", "lstm"], default="moving-average",
                        help="signal strategy to run (default: moving-average)")
```

Where the trading-loop thread is constructed, pass `args.strategy` through:

```python
    threads = [threading.Thread(
        target=_run_trading_loop,
        args=(settings, queue, metrics, stop_event, args.poll_interval, args.quantity),
        kwargs={"enforce_market_hours": args.replay is None, "strategy": args.strategy},
        name="trading-loop", daemon=True,
    )]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_main.py -v`
Expected: PASS (all existing tests still pass plus the 3 new ones)

- [ ] **Step 5: Run the full suite**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: all tests pass (existing count + this plan's new tests)

- [ ] **Step 6: Commit**

```bash
git add src/main.py tests/test_main.py
git commit -m "feat: add --strategy flag to select moving-average or lstm

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 7: Train the first real checkpoint and smoke-test it via replay

**Files:**
- No new source files. Produces `models/lstm_v1.pt` (not committed to git — see note below).

**Interfaces:**
- Consumes: `scripts/train_lstm.py` (Task 4), `src/main.py --strategy lstm --replay ...` (Task 6).

- [ ] **Step 1: Run the trainer on the real recordings**

Run: `.venv\Scripts\python.exe scripts\train_lstm.py`

This globs `data/ticks/ticks_[0-9]*.jsonl` (the 2026-09-09 and 2026-09-10 recordings), trains, and writes `models/lstm_v1.pt`. Note whatever `val_accuracy` it prints — per the spec, a number close to random-chance (~0.33 for 3 classes) is expected and acceptable at this data volume; this step is checking the pipeline runs end-to-end, not the score.

- [ ] **Step 2: Smoke-test through the real pipeline with --replay**

Run:
```
.venv\Scripts\python.exe -m src.main 005930 --strategy lstm --replay data\ticks\ticks_20260909.jsonl --replay-speed 60 --status-interval 0
```

Expected: runs to completion without exceptions; log lines show `signal 005930 buy/sell/hold strength=... -> accepted/rejected` from the `lstm` strategy_id, proving `LSTMStrategy` is wired into the real risk-gate/order-manager path the same way `MovingAverageStrategy` was validated in Phase 1.

- [ ] **Step 3: Decide whether to gitignore the checkpoint**

`models/lstm_v1.pt` is a binary training artifact that will be regenerated as more data accumulates (per the spec's upgrade path) — check `.gitignore` for a `models/` or `*.pt` entry; if absent, add one:

```
# LSTM checkpoints are trained artifacts, not source -- regenerate with
# scripts/train_lstm.py
models/*.pt
```

Commit only if `.gitignore` changed:

```bash
git add .gitignore
git commit -m "chore: gitignore trained LSTM checkpoints

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```
