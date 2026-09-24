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


def _zscore(values: list[float]) -> list[float]:
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    std = math.sqrt(variance)
    if std == 0.0:
        return [0.0 for _ in values]
    return [(v - mean) / std for v in values]


def normalize_window(price_window: list[float], volume_window: list[float]) -> list[list[float]]:
    base_price = price_window[0]
    price_returns = [(price - base_price) / base_price for price in price_window]
    log_volumes = [math.log1p(volume) for volume in volume_window]
    return [[p, v] for p, v in zip(_zscore(price_returns), _zscore(log_volumes))]


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
        if future_return > high_threshold:
            label = LABEL_BUY
        elif future_return < low_threshold:
            label = LABEL_SELL
        else:
            label = LABEL_HOLD
        features.append(normalize_window(price_window, volume_window))
        labels.append(label)

    X = np.array(features, dtype=np.float32).reshape(len(features), window_size, 2)
    y = np.array(labels, dtype=np.int64)
    return X, y
