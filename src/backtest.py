"""Offline backtester for tick strategies over recorded JSONL files.

Unlike ``--replay`` (src/main.py), this never touches Redis or the trade
ledger (``data/trading.sqlite3``): it feeds recorded ticks straight into a
strategy's ``on_tick`` and simulates fills in memory, so it is safe to run
any number of times and finishes at CPU speed instead of wall-clock speed.

Execution model (deliberately simple, long-only, one position per symbol):

- A BUY signal opens a position of ``quantity`` shares if none is held; a
  SELL signal closes the whole position.  Repeated BUYs while holding and
  SELLs while flat are ignored, matching how the paper portfolio rejects
  sells of shares it does not hold.
- Fills happen at the signal's tick price, worsened by ``slippage_ticks``
  KRX tick-size steps (buy higher, sell lower).
- Costs: ``commission_rate`` on both legs, ``sell_tax_rate`` on the sell
  leg.  The defaults are assumptions -- override them with the rates that
  actually apply to the account.
- Every position is closed at the last seen price at ``flatten_at`` (or at
  the last tick of the day), and every strategy is rebuilt at the start of
  each KST trading day, mirroring a fresh process per day in production.
- Optional risk limits mirror ``RiskGate``: ``min_strength``,
  ``max_order_value`` and ``max_daily_loss`` (gross losses, like
  ``daily_realized_loss``).  Once the loss limit is hit, new entries are
  blocked but exits still go through.
"""

from __future__ import annotations

import csv
import json
import statistics
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo

from src.models import Signal, SignalAction, Tick

KST = ZoneInfo("Asia/Seoul")

# KRX equity tick sizes (unified for KOSPI/KOSDAQ since 2023-01-25).
_TICK_SIZES = (
    (2_000, 1),
    (5_000, 5),
    (20_000, 10),
    (50_000, 50),
    (200_000, 100),
    (500_000, 500),
)


def krx_tick_size(price: float) -> int:
    for upper, size in _TICK_SIZES:
        if price < upper:
            return size
    return 1_000


class Strategy(Protocol):
    def on_tick(self, tick: Tick) -> Signal: ...


StrategyFactory = Callable[[], Strategy]


@dataclass(frozen=True)
class CostModel:
    commission_rate: float = 0.00015   # per leg, assumed broker fee
    sell_tax_rate: float = 0.0020      # securities transaction tax on sells, assumed
    slippage_ticks: int = 0

    def __post_init__(self) -> None:
        if self.commission_rate < 0 or self.sell_tax_rate < 0 or self.slippage_ticks < 0:
            raise ValueError("cost parameters cannot be negative")

    def buy_fill(self, price: float) -> float:
        return price + self.slippage_ticks * krx_tick_size(price)

    def sell_fill(self, price: float) -> float:
        return max(1.0, price - self.slippage_ticks * krx_tick_size(price))

    def costs(self, buy_value: float, sell_value: float) -> float:
        return (buy_value + sell_value) * self.commission_rate + sell_value * self.sell_tax_rate


@dataclass(frozen=True)
class BacktestConfig:
    quantity: int = 1
    min_strength: float = 0.0
    max_order_value: float = 0.0   # 0 disables
    max_daily_loss: float = 0.0    # 0 disables
    session_start: time = time(9, 0)
    session_end: time = time(15, 30)
    flatten_at: time | None = time(15, 20)
    symbols: frozenset[str] | None = None
    costs: CostModel = field(default_factory=CostModel)

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
        if self.session_start >= self.session_end:
            raise ValueError("session_start must be earlier than session_end")
        if self.max_order_value < 0 or self.max_daily_loss < 0:
            raise ValueError("limits cannot be negative")


@dataclass(frozen=True)
class RoundTrip:
    day: date
    symbol: str
    quantity: int
    entry_time: datetime
    entry_price: float
    exit_time: datetime
    exit_price: float
    entry_strength: float
    exit_reason: str          # "signal" or "flatten"
    gross_pnl: float
    costs: float

    @property
    def net_pnl(self) -> float:
        return self.gross_pnl - self.costs

    @property
    def hold_seconds(self) -> float:
        return (self.exit_time - self.entry_time).total_seconds()

    @property
    def gross_ticks(self) -> float:
        return (self.exit_price - self.entry_price) / krx_tick_size(self.entry_price)


@dataclass
class _Position:
    quantity: int
    price: float
    time: datetime
    strength: float


@dataclass
class BacktestResult:
    round_trips: list[RoundTrip] = field(default_factory=list)
    ticks: int = 0
    signals: int = 0
    rejected: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    days: list[date] = field(default_factory=list)


def iter_ticks(paths: Iterable[str | Path]) -> Iterator[Tick]:
    """Yield ticks from RecordingQueue JSONL files, skipping malformed lines."""
    for path in paths:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    payload = json.loads(line)["payload"]
                    yield Tick(symbol=str(payload["symbol"]), price=float(payload["price"]),
                               volume=int(payload["volume"]),
                               timestamp=datetime.fromisoformat(payload["timestamp"]))
                except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                    continue


class Backtester:
    def __init__(self, strategy_factory: StrategyFactory, config: BacktestConfig | None = None) -> None:
        self.strategy_factory = strategy_factory
        self.config = config or BacktestConfig()

    def run(self, ticks: Iterable[Tick]) -> BacktestResult:
        cfg = self.config
        result = BacktestResult()
        strategy: Strategy | None = None
        day: date | None = None
        positions: dict[str, _Position] = {}
        last_seen: dict[str, tuple[float, datetime]] = {}
        daily_loss = 0.0
        flattened = False

        def close(symbol: str, price: float, when: datetime, reason: str) -> None:
            nonlocal daily_loss
            position = positions.pop(symbol)
            exit_price = cfg.costs.sell_fill(price)
            buy_value = position.price * position.quantity
            sell_value = exit_price * position.quantity
            trip = RoundTrip(
                day=day, symbol=symbol, quantity=position.quantity,  # type: ignore[arg-type]
                entry_time=position.time, entry_price=position.price,
                exit_time=when, exit_price=exit_price, entry_strength=position.strength,
                exit_reason=reason, gross_pnl=sell_value - buy_value,
                costs=cfg.costs.costs(buy_value, sell_value),
            )
            result.round_trips.append(trip)
            if trip.net_pnl < 0:
                daily_loss += -trip.net_pnl

        def flatten_all() -> None:
            for symbol in list(positions):
                price, when = last_seen[symbol]
                close(symbol, price, when, "flatten")

        for tick in ticks:
            if cfg.symbols is not None and tick.symbol not in cfg.symbols:
                continue
            local = tick.timestamp.astimezone(KST)
            if not cfg.session_start <= local.time() < cfg.session_end:
                continue
            if local.date() != day:
                flatten_all()
                day = local.date()
                result.days.append(day)
                strategy = self.strategy_factory()
                daily_loss = 0.0
                flattened = False

            result.ticks += 1
            last_seen[tick.symbol] = (tick.price, tick.timestamp)
            signal = strategy.on_tick(tick)  # type: ignore[union-attr]

            if cfg.flatten_at is not None and local.time() >= cfg.flatten_at:
                if not flattened:
                    flatten_all()
                    flattened = True
                continue
            if signal.action == SignalAction.HOLD:
                continue
            result.signals += 1
            if signal.strength < cfg.min_strength:
                result.rejected["min_strength"] += 1
                continue

            held = positions.get(signal.symbol)
            if signal.action == SignalAction.SELL:
                if held is not None:
                    close(signal.symbol, signal.price, tick.timestamp, "signal")
                continue
            if held is not None:
                continue
            if cfg.max_daily_loss and daily_loss >= cfg.max_daily_loss:
                result.rejected["daily_loss"] += 1
                continue
            fill = cfg.costs.buy_fill(signal.price)
            if cfg.max_order_value and fill * cfg.quantity > cfg.max_order_value:
                result.rejected["order_value"] += 1
                continue
            positions[signal.symbol] = _Position(cfg.quantity, fill, tick.timestamp, signal.strength)

        flatten_all()
        return result


@dataclass(frozen=True)
class Summary:
    label: str
    trades: int
    win_rate: float
    gross_pnl: float
    costs: float
    net_pnl: float
    avg_net_pnl: float
    avg_gross_ticks: float
    median_hold_seconds: float

    @classmethod
    def of(cls, label: str, trips: list[RoundTrip]) -> "Summary":
        if not trips:
            return cls(label, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        net = [t.net_pnl for t in trips]
        return cls(
            label=label, trades=len(trips),
            win_rate=sum(n > 0 for n in net) / len(trips),
            gross_pnl=sum(t.gross_pnl for t in trips),
            costs=sum(t.costs for t in trips),
            net_pnl=sum(net),
            avg_net_pnl=sum(net) / len(trips),
            avg_gross_ticks=statistics.fmean(t.gross_ticks for t in trips),
            median_hold_seconds=statistics.median(t.hold_seconds for t in trips),
        )


def summarize(result: BacktestResult, key: Callable[[RoundTrip], object] | None = None) -> list[Summary]:
    if key is None:
        return [Summary.of("total", result.round_trips)]
    groups: dict[object, list[RoundTrip]] = defaultdict(list)
    for trip in result.round_trips:
        groups[key(trip)].append(trip)
    return [Summary.of(str(k), v) for k, v in sorted(groups.items(), key=lambda item: str(item[0]))]


def format_table(rows: list[Summary], title: str) -> str:
    header = (f"{title:<12} {'trades':>7} {'win%':>6} {'gross':>12} {'costs':>11} "
              f"{'net':>12} {'avg_net':>9} {'avg_tick':>8} {'hold_med':>8}")
    lines = [header, "-" * len(header)]
    for r in rows:
        lines.append(
            f"{r.label:<12} {r.trades:>7} {r.win_rate * 100:>5.1f}% {r.gross_pnl:>12,.0f} "
            f"{r.costs:>11,.0f} {r.net_pnl:>12,.0f} {r.avg_net_pnl:>9,.0f} "
            f"{r.avg_gross_ticks:>8.2f} {r.median_hold_seconds:>7.0f}s"
        )
    return "\n".join(lines)


def write_trades_csv(result: BacktestResult, path: str | Path) -> None:
    columns = list(RoundTrip.__dataclass_fields__) + ["net_pnl", "hold_seconds", "gross_ticks"]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for trip in result.round_trips:
            row = asdict(trip)
            row.update(net_pnl=trip.net_pnl, hold_seconds=trip.hold_seconds,
                       gross_ticks=trip.gross_ticks)
            writer.writerow(row)
