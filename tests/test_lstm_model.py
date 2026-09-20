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
