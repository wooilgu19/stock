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
