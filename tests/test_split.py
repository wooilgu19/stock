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
