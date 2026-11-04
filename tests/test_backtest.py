import json
from datetime import datetime, time, timedelta, timezone

import pytest

from src.backtest import (
    Backtester, BacktestConfig, CostModel, iter_ticks, krx_tick_size, summarize, write_trades_csv,
)
from src.models import Signal, SignalAction, Tick

NO_COSTS = CostModel(commission_rate=0, sell_tax_rate=0)
# 2026-11-02 09:10 KST
BASE = datetime(2026, 11, 2, 0, 10, tzinfo=timezone.utc)


class Scripted:
    """Emits a fixed action per price: 'b'uy / 's'ell / anything else HOLD."""

    def __init__(self, actions: dict[float, str], strength: float = 0.7) -> None:
        self.actions = actions
        self.strength = strength

    def on_tick(self, tick: Tick) -> Signal:
        code = self.actions.get(tick.price)
        action = {"b": SignalAction.BUY, "s": SignalAction.SELL}.get(code, SignalAction.HOLD)
        strength = self.strength if action != SignalAction.HOLD else 0.0
        return Signal(tick.symbol, action, strength, tick.price, "scripted", tick.timestamp)


def ticks(prices, start=BASE, symbol="005930", step=60):
    return [Tick(symbol, p, 1, start + timedelta(seconds=i * step)) for i, p in enumerate(prices)]


def run(prices_or_ticks, actions, config=None, strength=0.7):
    data = prices_or_ticks if prices_or_ticks and isinstance(prices_or_ticks[0], Tick) else ticks(prices_or_ticks)
    config = config or BacktestConfig(costs=NO_COSTS)
    return Backtester(lambda: Scripted(actions, strength), config).run(data)


@pytest.mark.parametrize("price,size", [
    (1_999, 1), (2_000, 5), (4_999, 5), (5_000, 10), (20_000, 50), (50_000, 100),
    (199_999, 100), (200_000, 500), (499_999, 500), (500_000, 1_000), (1_400_000, 1_000),
])
def test_krx_tick_size(price, size):
    assert krx_tick_size(price) == size


def test_buy_then_sell_records_one_round_trip():
    result = run([100, 101, 103], {101: "b", 103: "s"})
    [trip] = result.round_trips
    assert (trip.entry_price, trip.exit_price, trip.gross_pnl) == (101, 103, 2)
    assert trip.exit_reason == "signal"
    assert trip.hold_seconds == 60


def test_repeated_buys_and_sells_while_flat_are_ignored():
    result = run([99, 100, 101, 102, 103], {99: "s", 100: "b", 101: "b", 102: "s", 103: "s"})
    [trip] = result.round_trips
    assert (trip.entry_price, trip.exit_price) == (100, 102)


def test_costs_and_slippage():
    costs = CostModel(commission_rate=0.001, sell_tax_rate=0.002, slippage_ticks=1)
    result = run([10_000, 10_100], {10_000: "b", 10_100: "s"}, BacktestConfig(costs=costs))
    [trip] = result.round_trips
    assert trip.entry_price == 10_010 and trip.exit_price == 10_090
    assert trip.gross_pnl == 80
    assert trip.costs == pytest.approx((10_010 + 10_090) * 0.001 + 10_090 * 0.002)
    assert trip.net_pnl == pytest.approx(80 - trip.costs)


def test_open_position_is_flattened_at_flatten_time():
    # 15:15, 15:19, 15:20, 15:25 KST
    start = datetime(2026, 11, 2, 6, 15, tzinfo=timezone.utc)
    data = [Tick("005930", p, 1, start + timedelta(minutes=m)) for p, m in
            [(100, 0), (101, 4), (102, 5), (90, 10)]]
    result = run(data, {100: "b", 90: "b"})
    [trip] = result.round_trips
    assert trip.exit_reason == "flatten"
    assert trip.exit_price == 102  # price at the flatten tick; the later BUY is blocked


def test_position_is_flattened_and_strategy_rebuilt_at_day_change():
    built = []

    def factory():
        built.append(1)
        return Scripted({100: "b"})

    day1 = ticks([100, 105])
    day2 = ticks([107], start=BASE + timedelta(days=1))
    result = Backtester(factory, BacktestConfig(costs=NO_COSTS, flatten_at=None)).run(day1 + day2)
    [trip] = result.round_trips
    assert trip.exit_reason == "flatten" and trip.exit_price == 105
    assert len(built) == 2 and len(result.days) == 2


def test_ticks_outside_session_and_other_symbols_are_skipped():
    early = Tick("005930", 100, 1, datetime(2026, 11, 2, 23, 50, tzinfo=timezone.utc) - timedelta(days=1))
    other = Tick("000660", 100, 1, BASE)
    result = run([early, other], {100: "b"},
                 BacktestConfig(costs=NO_COSTS, symbols=frozenset({"005930"})))
    assert result.ticks == 0 and result.round_trips == []


def test_min_strength_rejects_weak_signals():
    result = run([100, 101], {100: "b", 101: "s"},
                 BacktestConfig(costs=NO_COSTS, min_strength=0.8), strength=0.7)
    assert result.round_trips == []
    assert result.rejected["min_strength"] == 2  # weak exits are rejected too, like RiskGate


def test_max_order_value_blocks_expensive_entries():
    result = run([1_400_000, 1_390_000], {1_400_000: "b", 1_390_000: "s"},
                 BacktestConfig(costs=NO_COSTS, max_order_value=1_000_000))
    assert result.round_trips == [] and result.rejected["order_value"] == 1


def test_daily_loss_limit_blocks_entries_but_allows_exits_and_resets_next_day():
    actions = {100: "b", 90: "s", 95: "b", 96: "s"}
    cfg = BacktestConfig(costs=NO_COSTS, max_daily_loss=10, flatten_at=None)
    day1 = ticks([100, 90, 95, 96])
    day2 = ticks([95, 96], start=BASE + timedelta(days=1))
    result = run(day1 + day2, actions, cfg)
    assert [t.gross_pnl for t in result.round_trips] == [-10, 1]
    assert result.rejected["daily_loss"] == 1
    assert result.round_trips[1].day != result.round_trips[0].day


def test_summary_and_grouping():
    result = run([100, 101, 102, 101, 100], {100: "b", 102: "s", 101: "s"})
    # buy 100 -> sell 101 (+1); buy 100 at end -> flatten at 100 (0)
    [total] = summarize(result)
    assert total.trades == 2 and total.gross_pnl == 1 and total.win_rate == 0.5
    [by_symbol] = summarize(result, key=lambda t: t.symbol)
    assert by_symbol.label == "005930"


def test_config_validation():
    with pytest.raises(ValueError):
        BacktestConfig(quantity=0)
    with pytest.raises(ValueError):
        BacktestConfig(session_start=time(15, 30), session_end=time(9, 0))
    with pytest.raises(ValueError):
        CostModel(slippage_ticks=-1)


def test_iter_ticks_reads_recordings_and_skips_bad_lines(tmp_path):
    path = tmp_path / "ticks_20261102.jsonl"
    good = {"ts": 1.0, "payload": {"symbol": "005930", "price": 100.0, "volume": 3,
                                   "timestamp": "2026-11-02T00:10:00+00:00"}}
    path.write_text("\n".join([json.dumps(good), "not json",
                               json.dumps({"ts": 2.0, "payload": {"symbol": "005930"}})]),
                    encoding="utf-8")
    [tick] = list(iter_ticks([path]))
    assert (tick.symbol, tick.price, tick.volume) == ("005930", 100.0, 3)


def test_write_trades_csv(tmp_path):
    result = run([100, 101], {100: "b", 101: "s"})
    out = tmp_path / "trades.csv"
    write_trades_csv(result, out)
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and "net_pnl" in lines[0]


def test_cli_runs_end_to_end(tmp_path, capsys):
    from scripts.backtest import main

    path = tmp_path / "ticks_20261102.jsonl"
    rows = []
    for i, price in enumerate([100, 100, 100, 101, 102, 101, 100, 99, 100, 101]):
        ts = (BASE + timedelta(seconds=i)).isoformat()
        rows.append(json.dumps({"ts": i, "payload": {"symbol": "005930", "price": price,
                                                     "volume": 1, "timestamp": ts}}))
    path.write_text("\n".join(rows), encoding="utf-8")
    assert main([str(path), "--short", "2", "--long", "3", "--by", "symbol"]) == 0
    out = capsys.readouterr().out
    assert "days=1" in out and "005930" in out
