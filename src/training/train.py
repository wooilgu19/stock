"""Offline training entrypoint: recorded tick files -> models/lstm_v1.pt.

Each file is one recording day. With more than one day available, whole
days are held out for validation (day-level holdout) instead of splitting
within a day: splitting within a day lets validation windows sit right
after training windows from the same trend/regime, so the model can score
well by extrapolating that day's own trend rather than generalizing across
days. With only one day available there is no other day to hold out, so
that single file falls back to chronological_split's within-day split.
"""

import json
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from src.training.model import LSTMClassifier
from src.training.split import chronological_split
from src.training.windowing import build_dataset, compute_future_returns


def _load_ticks(path: Path) -> dict[str, tuple[list[float], list[float]]]:
    """Group ticks by symbol so a multi-symbol recording never interleaves
    unrelated price series (RecordingQueue.publish writes every subscribed
    symbol's ticks into the same file). JSONL lines are already chronological
    (append-only), so filtering by symbol preserves per-symbol order."""
    series: dict[str, tuple[list[float], list[float]]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)["payload"]
        symbol = payload["symbol"]
        prices, volumes = series.setdefault(symbol, ([], []))
        prices.append(float(payload["price"]))
        volumes.append(float(payload["volume"]))
    return series


def run_training(ticks_paths: list[Path], window_size: int, lookahead: int, val_ratio: float,
                  epochs: int, lr: float, output_path: Path, hidden_size: int = 16,
                  num_layers: int = 1, dropout: float = 0.2, low_quantile: float = 0.3,
                  high_quantile: float = 0.7, seed: int = 42, batch_size: int = 64) -> dict:
    torch.manual_seed(seed)

    sorted_paths = sorted(Path(p) for p in ticks_paths)

    if len(sorted_paths) > 1:
        num_val_files = min(len(sorted_paths) - 1, max(1, round(len(sorted_paths) * val_ratio)))
        train_paths, val_paths = sorted_paths[:-num_val_files], sorted_paths[-num_val_files:]
        train_series = [series for p in train_paths for series in _load_ticks(p).values()]
        val_series = [series for p in val_paths for series in _load_ticks(p).values()]
    else:
        train_series, val_series = [], []
        for prices, volumes in _load_ticks(sorted_paths[0]).values():
            (train_p, train_v), (val_p, val_v) = chronological_split(
                prices, volumes, val_ratio=val_ratio, lookahead=lookahead)
            train_series.append((train_p, train_v))
            val_series.append((val_p, val_v))

    # Thresholds are computed from train-side returns only, across every
    # file, so validation never influences where the label boundaries fall.
    all_train_returns: list[float] = []
    for train_prices, _ in train_series:
        all_train_returns.extend(
            r for r in compute_future_returns(train_prices, window_size, lookahead) if r is not None
        )
    low_threshold = float(np.quantile(all_train_returns, low_quantile))
    high_threshold = float(np.quantile(all_train_returns, high_quantile))

    train_X_parts, train_y_parts = [], []
    for train_prices, train_volumes in train_series:
        tx, ty = build_dataset(train_prices, train_volumes, window_size, lookahead,
                                low_threshold, high_threshold)
        train_X_parts.append(tx)
        train_y_parts.append(ty)

    val_X_parts, val_y_parts = [], []
    for val_prices, val_volumes in val_series:
        vx, vy = build_dataset(val_prices, val_volumes, window_size, lookahead,
                                low_threshold, high_threshold)
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
    train_loader = DataLoader(TensorDataset(train_X_t, train_y_t), batch_size=batch_size,
                               shuffle=True, generator=torch.Generator().manual_seed(seed))

    model.train()
    for _ in range(epochs):
        for batch_X, batch_y in train_loader:
            optimizer.zero_grad()
            logits = model(batch_X)
            loss = loss_fn(logits, batch_y)
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

    val_counts = np.bincount(val_y, minlength=3) if len(val_y) else np.zeros(3, dtype=int)
    majority_baseline = float(val_counts.max() / len(val_y)) if len(val_y) else 0.0
    return {"train_size": len(train_y), "val_size": len(val_y), "val_accuracy": val_accuracy,
            "val_label_counts": val_counts.tolist(), "majority_baseline": majority_baseline}
