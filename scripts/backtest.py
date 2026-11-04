"""CLI for the offline backtester (src/backtest.py).

Never writes to data/trading.sqlite3 or Redis -- safe to run any time.

Examples:
    .venv\\Scripts\\python.exe scripts\\backtest.py
    .venv\\Scripts\\python.exe scripts\\backtest.py --symbols 005930 --short 200 --long 1000
    .venv\\Scripts\\python.exe scripts\\backtest.py --strategy lstm --model models\\lstm_20261025_seed1.pt
    # mirror the live paper settings (09:00-20:00, flatten 19:50, RiskGate limits, no costs):
    .venv\\Scripts\\python.exe scripts\\backtest.py --end 20:00 --flatten-at 19:50 \\
        --min-strength 0.60 --max-order-value 1000000 --max-daily-loss 100000 \\
        --commission 0 --sell-tax 0
"""

import argparse
import sys
from datetime import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.backtest import (  # noqa: E402
    Backtester, BacktestConfig, CostModel, format_table, iter_ticks, summarize, write_trades_csv,
)


def _clock(value: str) -> time:
    try:
        return time.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected HH:MM, got {value!r}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backtest a tick strategy on recorded ticks (no DB writes)")
    parser.add_argument("files", nargs="*", help="tick JSONL files (default: --ticks-glob)")
    parser.add_argument("--ticks-glob", default="data/ticks/ticks_[0-9]*.jsonl")
    parser.add_argument("--symbols", nargs="+", help="only these symbols (default: all)")

    strategy = parser.add_argument_group("strategy")
    strategy.add_argument("--strategy", choices=["moving-average", "lstm"], default="moving-average")
    strategy.add_argument("--short", type=int, default=5, help="moving-average short window (ticks)")
    strategy.add_argument("--long", type=int, default=20, help="moving-average long window (ticks)")
    strategy.add_argument("--model", default="models/lstm_v1.pt", help="LSTM checkpoint")

    execution = parser.add_argument_group("execution")
    execution.add_argument("--quantity", type=int, default=1)
    execution.add_argument("--start", type=_clock, default=time(9, 0), help="KST session start")
    execution.add_argument("--end", type=_clock, default=time(15, 30), help="KST session end")
    execution.add_argument("--flatten-at", default="15:20",
                           help="KST time to close all positions, or 'off'")
    execution.add_argument("--min-strength", type=float, default=0.0)
    execution.add_argument("--max-order-value", type=float, default=0.0, help="0 = no limit")
    execution.add_argument("--max-daily-loss", type=float, default=0.0, help="0 = no limit")

    costs = parser.add_argument_group("costs (defaults are assumptions; set the real rates)")
    costs.add_argument("--commission", type=float, default=0.00015, help="fee rate per leg")
    costs.add_argument("--sell-tax", type=float, default=0.0020, help="tax rate on sells")
    costs.add_argument("--slippage-ticks", type=int, default=0,
                       help="KRX tick steps against us on each fill")

    output = parser.add_argument_group("output")
    output.add_argument("--by", choices=["day", "symbol", "both"], default="both")
    output.add_argument("--trades-csv", help="write every round trip to this CSV")
    return parser


def _strategy_factory(args: argparse.Namespace):
    if args.strategy == "lstm":
        from src.strategies.lstm_strategy import LSTMStrategy  # heavy torch import
        return lambda: LSTMStrategy(model_path=args.model)
    from src.strategies.moving_average import MovingAverageStrategy
    MovingAverageStrategy(short_window=args.short, long_window=args.long)  # validate early
    return lambda: MovingAverageStrategy(short_window=args.short, long_window=args.long)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    paths = [Path(p) for p in args.files] or sorted(Path().glob(args.ticks_glob))
    if not paths:
        parser.error(f"no tick files matched {args.ticks_glob!r}")
    flatten_at = None if args.flatten_at.lower() == "off" else _clock(args.flatten_at)

    try:
        config = BacktestConfig(
            quantity=args.quantity, min_strength=args.min_strength,
            max_order_value=args.max_order_value, max_daily_loss=args.max_daily_loss,
            session_start=args.start, session_end=args.end, flatten_at=flatten_at,
            symbols=frozenset(args.symbols) if args.symbols else None,
            costs=CostModel(commission_rate=args.commission, sell_tax_rate=args.sell_tax,
                            slippage_ticks=args.slippage_ticks),
        )
        factory = _strategy_factory(args)
    except (ValueError, FileNotFoundError) as exc:
        parser.error(str(exc))

    print(f"backtesting {args.strategy} on {len(paths)} file(s)", file=sys.stderr)
    result = Backtester(factory, config).run(iter_ticks(paths))

    print(f"days={len(result.days)} ticks={result.ticks:,} signals={result.signals:,} "
          f"rejected={dict(result.rejected)}")
    if args.by in ("day", "both"):
        print()
        print(format_table(summarize(result, key=lambda t: t.day.isoformat()), "day"))
    if args.by in ("symbol", "both"):
        print()
        print(format_table(summarize(result, key=lambda t: t.symbol), "symbol"))
    print()
    print(format_table(summarize(result), "all"))
    if args.trades_csv:
        write_trades_csv(result, args.trades_csv)
        print(f"wrote {len(result.round_trips)} round trips to {args.trades_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
