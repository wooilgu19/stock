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
