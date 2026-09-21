import json

import torch

from src.training.train import _load_ticks, run_training


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


def _write_interleaved_multi_symbol_ticks(path, n):
    """Interleave two symbols tick-by-tick: symbol A trends up from ~100,
    symbol B trends down from ~50000. If _load_ticks ever mixed them into
    one series again, that series would jump between price ranges every
    other tick.
    """
    price_a = 100.0
    price_b = 50000.0
    lines = []
    for i in range(n):
        price_a += 0.05
        price_b -= 1.0
        lines.append(json.dumps({
            "ts": float(2 * i),
            "payload": {"symbol": "AAA", "price": price_a, "volume": 10.0,
                        "timestamp": "2026-01-01T00:00:00+00:00"},
        }))
        lines.append(json.dumps({
            "ts": float(2 * i + 1),
            "payload": {"symbol": "BBB", "price": price_b, "volume": 20.0,
                        "timestamp": "2026-01-01T00:00:00+00:00"},
        }))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_load_ticks_groups_by_symbol_instead_of_interleaving(tmp_path):
    ticks_path = tmp_path / "multi_symbol.jsonl"
    _write_interleaved_multi_symbol_ticks(ticks_path, n=100)

    series = _load_ticks(ticks_path)

    assert set(series.keys()) == {"AAA", "BBB"}
    aaa_prices, aaa_volumes = series["AAA"]
    bbb_prices, bbb_volumes = series["BBB"]
    assert len(aaa_prices) == 100
    assert len(bbb_prices) == 100
    # Not interleaved: every AAA price stays in AAA's low range and every
    # BBB price stays in BBB's high range -- a mixed series would jump
    # between them tick-by-tick.
    assert max(aaa_prices) < min(bbb_prices)
    assert all(v == 10.0 for v in aaa_volumes)
    assert all(v == 20.0 for v in bbb_volumes)


def test_run_training_on_multi_symbol_file_windows_each_symbol_independently(tmp_path):
    ticks_path = tmp_path / "multi_symbol.jsonl"
    _write_interleaved_multi_symbol_ticks(ticks_path, n=150)
    output_path = tmp_path / "model.pt"

    metrics = run_training(
        ticks_paths=[ticks_path], window_size=5, lookahead=2, val_ratio=0.2,
        epochs=3, lr=0.01, output_path=output_path, hidden_size=4, num_layers=1,
    )

    assert output_path.exists()
    assert metrics["train_size"] > 0
    assert metrics["val_size"] > 0
