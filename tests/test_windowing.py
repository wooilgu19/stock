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


def test_normalize_window_zscores_price_returns_and_log_volume_per_channel():
    result = normalize_window([100.0, 101.0, 99.0], [10.0, 20.0, 0.0])

    prices, volumes = zip(*result)
    assert prices == pytest.approx([0.0, 1.224745, -1.224745], abs=1e-5)
    assert sum(prices) == pytest.approx(0.0, abs=1e-9)
    assert sum(volumes) == pytest.approx(0.0, abs=1e-9)


def test_normalize_window_returns_zero_for_a_constant_channel():
    result = normalize_window([100.0, 100.0, 100.0], [10.0, 10.0, 10.0])
    assert result == [[0.0, 0.0], [0.0, 0.0], [0.0, 0.0]]


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
