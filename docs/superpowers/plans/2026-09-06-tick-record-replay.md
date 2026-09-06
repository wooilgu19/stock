# Tick Record/Replay (Off-Hours Observation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user record live KIS ticks during weekday market hours and replay them at their original pace outside market hours, so the trading pipeline (signal → risk gate → order) can be observed with real market data at night or on weekends.

**Architecture:** A thin `RecordingQueue` wraps the existing `RedisQueue` to also append every published tick to a JSONL file (used during live weekday runs). A new `replay_ticks` coroutine reads that JSONL file back and republishes each tick to the same Redis stream at the recorded pace, standing in for the live KIS websocket collector. `src/main.py` gains `--record`/`--replay` flags to wire these in. Because both paths publish through the same Redis stream, the trading loop (`build_runtime`) needs no changes — except for one bypass: `OrderManager` checks wall-clock market hours, which would reject every order during an off-hours replay, so `build_order_manager`/`build_pipeline`/`build_runtime` gain an `enforce_market_hours` flag that `--replay` sets to `False`.

**Tech Stack:** Python 3, asyncio, Redis Streams (existing `RedisQueue`), pytest + `monkeypatch`.

**Spec:** `docs/superpowers/specs/2026-09-06-tick-record-replay-design.md`

## Global Constraints

- No new dependencies — stdlib `json`/`asyncio` only.
- `RecordingQueue` file-write failures must never block the live publish path (log and continue).
- Replay file empty or unparseable on the first line raises `ValueError` immediately — never a silent no-op.
- `--record` and `--replay` are mutually exclusive — passing both is a startup error (`SystemExit`).
- Live (non-replay) runs must keep `enforce_market_hours=True` by default — no behavior change for existing usage.

---

## File Structure

- **Create** `src/queue/recording_queue.py` — `RecordingQueue` wrapper class.
- **Create** `tests/test_recording_queue.py` — unit tests for `RecordingQueue`.
- **Create** `src/replay.py` — `replay_ticks` coroutine.
- **Create** `tests/test_replay.py` — unit tests for `replay_ticks`.
- **Modify** `src/application.py` — add `enforce_market_hours` parameter threaded through `build_order_manager`, `build_pipeline`, `build_runtime`.
- **Modify** `tests/test_application.py` — cover `enforce_market_hours=False`.
- **Modify** `src/main.py` — add `--record`/`--replay` CLI flags and wire `RecordingQueue`/`replay_ticks`/`enforce_market_hours` into `main()`.
- **Modify** `tests/test_main.py` — cover new CLI flags and wiring.

---

## Task 1: `RecordingQueue` wrapper

**Files:**
- Create: `src/queue/recording_queue.py`
- Test: `tests/test_recording_queue.py`

**Interfaces:**
- Consumes: nothing new — wraps any object exposing `publish(message: dict) -> str` (matches `RedisQueue.publish`, see `src/queue/redis_queue.py:36`).
- Produces: `RecordingQueue(inner, path)` with `.publish(message: dict) -> str`, used by Task 4 (`src/main.py`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_recording_queue.py
import json

from src.queue.recording_queue import RecordingQueue


class FakeQueue:
    def __init__(self):
        self.published = []

    def publish(self, message):
        self.published.append(message)
        return "1-0"


def test_publish_forwards_to_inner_queue_and_returns_its_id(tmp_path):
    inner = FakeQueue()
    recorder = RecordingQueue(inner, tmp_path / "ticks.jsonl")

    result = recorder.publish({"symbol": "005930", "price": 70000})

    assert result == "1-0"
    assert inner.published == [{"symbol": "005930", "price": 70000}]


def test_publish_appends_one_jsonl_line_per_call(tmp_path):
    inner = FakeQueue()
    path = tmp_path / "ticks.jsonl"
    recorder = RecordingQueue(inner, path)

    recorder.publish({"symbol": "005930", "price": 70000})
    recorder.publish({"symbol": "005930", "price": 70100})

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["payload"] == {"symbol": "005930", "price": 70000}
    assert isinstance(first["ts"], (int, float))


def test_publish_still_succeeds_when_file_write_fails(tmp_path, monkeypatch):
    inner = FakeQueue()
    recorder = RecordingQueue(inner, tmp_path / "ticks.jsonl")

    def broken_open(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("builtins.open", broken_open)

    result = recorder.publish({"symbol": "005930", "price": 70000})

    assert result == "1-0"
    assert inner.published == [{"symbol": "005930", "price": 70000}]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_recording_queue.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.queue.recording_queue'`

- [ ] **Step 3: Write the implementation**

```python
# src/queue/recording_queue.py
"""Wraps a tick queue to also append every published message to a JSONL file.

Used during live weekday runs (via ``src.main --record``) so the exact tick
stream can be replayed later outside market hours through
``src.replay.replay_ticks``.
"""

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class RecordingQueue:
    def __init__(self, inner: Any, path: str | Path) -> None:
        self.inner = inner
        self.path = Path(path)

    def publish(self, message: dict[str, Any]) -> str:
        result = self.inner.publish(message)
        try:
            line = json.dumps({"ts": time.time(), "payload": message})
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError:
            logger.warning("failed to record tick to %s", self.path, exc_info=True)
        return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_recording_queue.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/queue/recording_queue.py tests/test_recording_queue.py
git commit -m "feat: add RecordingQueue to capture ticks alongside live publishing"
```

---

## Task 2: `replay_ticks` coroutine

**Files:**
- Create: `src/replay.py`
- Test: `tests/test_replay.py`

**Interfaces:**
- Consumes: a JSONL file of `{"ts": float, "payload": dict}` lines (produced by `RecordingQueue` from Task 1); any object exposing `publish(message: dict) -> str` (e.g. `RedisQueue`, or the queue param already used by `_run_collector` in `src/main.py`).
- Produces: `async def replay_ticks(path: str | Path, queue: Any, stop_event: threading.Event) -> None`, used by Task 4 (`src/main.py`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_replay.py
import asyncio
import json
import threading

import pytest

from src.replay import replay_ticks


class FakeQueue:
    def __init__(self):
        self.published = []

    def publish(self, message):
        self.published.append(message)
        return "1-0"


def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def test_replay_publishes_each_payload_in_order(tmp_path):
    path = tmp_path / "ticks.jsonl"
    write_jsonl(path, [
        {"ts": 100.0, "payload": {"symbol": "005930", "price": 70000}},
        {"ts": 100.0, "payload": {"symbol": "005930", "price": 70100}},
    ])
    queue = FakeQueue()

    asyncio.run(replay_ticks(path, queue, threading.Event()))

    assert queue.published == [
        {"symbol": "005930", "price": 70000},
        {"symbol": "005930", "price": 70100},
    ]


def test_replay_sleeps_for_the_recorded_gap_between_ticks(tmp_path, monkeypatch):
    path = tmp_path / "ticks.jsonl"
    write_jsonl(path, [
        {"ts": 100.0, "payload": {"symbol": "005930", "price": 70000}},
        {"ts": 102.5, "payload": {"symbol": "005930", "price": 70100}},
    ])
    queue = FakeQueue()
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr("src.replay.asyncio.sleep", fake_sleep)

    asyncio.run(replay_ticks(path, queue, threading.Event()))

    assert sleeps == [2.5]


def test_replay_stops_promptly_when_stop_event_is_set(tmp_path, monkeypatch):
    path = tmp_path / "ticks.jsonl"
    write_jsonl(path, [
        {"ts": 100.0, "payload": {"symbol": "005930", "price": 70000}},
        {"ts": 200.0, "payload": {"symbol": "005930", "price": 70100}},
        {"ts": 300.0, "payload": {"symbol": "005930", "price": 70200}},
    ])
    queue = FakeQueue()
    stop_event = threading.Event()

    async def fake_sleep(seconds):
        stop_event.set()

    monkeypatch.setattr("src.replay.asyncio.sleep", fake_sleep)

    asyncio.run(replay_ticks(path, queue, stop_event))

    assert queue.published == [{"symbol": "005930", "price": 70000}]


def test_replay_raises_on_empty_file(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="empty"):
        asyncio.run(replay_ticks(path, FakeQueue(), threading.Event()))


def test_replay_raises_on_malformed_first_line(tmp_path):
    path = tmp_path / "broken.jsonl"
    path.write_text("not json\n", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid"):
        asyncio.run(replay_ticks(path, FakeQueue(), threading.Event()))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_replay.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.replay'`

- [ ] **Step 3: Write the implementation**

```python
# src/replay.py
"""Replays a JSONL tick recording (from RecordingQueue) back onto a queue.

Stands in for the live KIS websocket collector in src.main when running
with --replay, so the trading loop can be observed outside market hours
using previously recorded real ticks.
"""

import asyncio
import json
import threading
from pathlib import Path
from typing import Any


async def replay_ticks(path: str | Path, queue: Any, stop_event: threading.Event) -> None:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ValueError(f"replay file is empty: {path}")

    rows = []
    for line in lines:
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid replay line in {path}: {line!r}") from exc

    previous_ts = rows[0]["ts"]
    for row in rows:
        if stop_event.is_set():
            return
        gap = row["ts"] - previous_ts
        if gap > 0:
            await asyncio.sleep(gap)
        previous_ts = row["ts"]
        queue.publish(row["payload"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_replay.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/replay.py tests/test_replay.py
git commit -m "feat: add replay_ticks to republish recorded ticks at their original pace"
```

---

## Task 3: `enforce_market_hours` bypass in application wiring

**Files:**
- Modify: `src/application.py:30-67` (`build_order_manager`, `build_pipeline`, `build_runtime`)
- Modify: `tests/test_application.py`

**Interfaces:**
- Consumes: `MarketHours.from_settings(settings)` (existing, `src/engine/market_hours.py:18`); `OrderManager(..., market_hours: MarketHours | None = None, ...)` (existing, `src/engine/order_manager.py:32-42`).
- Produces: `build_order_manager(settings, session=None, enforce_market_hours=True)`, `build_pipeline(settings, predictor, queue=None, quantity=1, on_result=None, enforce_market_hours=True)`, `build_runtime(settings, predictor, queue=None, quantity=1, on_result=None, poll_interval=1.0, reconciler=None, metrics=None, on_error=None, enforce_market_hours=True)` — all default `True` (no behavior change for existing callers). Used by Task 4 (`src/main.py`).

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_application.py
def test_build_order_manager_skips_market_hours_check_when_disabled(tmp_path):
    manager = build_order_manager(
        Settings(database_path=tmp_path / "trades.sqlite3", paper_starting_cash=500_000),
        enforce_market_hours=False,
    )

    assert manager.market_hours is None


def test_build_order_manager_enforces_market_hours_by_default(tmp_path):
    manager = build_order_manager(
        Settings(database_path=tmp_path / "trades.sqlite3", paper_starting_cash=500_000),
    )

    assert manager.market_hours is not None
```

(`build_order_manager` is already imported at the top of `tests/test_application.py:5`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_application.py -k enforce_market_hours -v`
Expected: FAIL with `TypeError: build_order_manager() got an unexpected keyword argument 'enforce_market_hours'`

- [ ] **Step 3: Write the implementation**

In `src/application.py`, change the three function signatures and thread the flag through:

```python
def build_order_manager(settings: Settings, session: Any = None,
                        enforce_market_hours: bool = True) -> OrderManager:
    """Build a paper-safe order manager from application settings.

    Paper mode does not need credentials or an executor.  Live mode validates
    credentials and injects the KIS executor, but still performs no API call
    until ``OrderManager.submit`` is invoked. ``enforce_market_hours=False``
    skips the wall-clock market-hours check entirely — used when replaying
    recorded ticks outside trading hours (see src/replay.py), where the
    replay's real-time clock legitimately disagrees with the ticks' original
    market time.
    """
    repository = TradeRepository(settings.database_path)
    executor = None
    if not settings.is_paper:
        settings.validate_for_live()
        client = KISRestClient(
            settings.kis_base_url,
            settings.kis_appkey,
            settings.kis_appsecret,
            session=session,
        )
        executor = KISOrderExecutor(
            client,
            settings.kis_cano,
            settings.kis_acnt_prdt_cd,
            paper_trading=False,
        )

    return OrderManager(
        repository=repository,
        risk_gate=RiskGate(
            settings.min_signal_strength,
            settings.max_order_value,
            settings.max_daily_loss,
        ),
        paper_trading=settings.is_paper,
        market_hours=MarketHours.from_settings(settings) if enforce_market_hours else None,
        portfolio=(
            PortfolioState.from_repository(repository, settings.paper_starting_cash)
            if settings.is_paper else None
        ),
        executor=executor,
    )
```

```python
def build_pipeline(settings: Settings, predictor: SignalPredictor,
                   queue: TickQueue | None = None, quantity: Any = 1,
                   on_result: Any = None, enforce_market_hours: bool = True) -> InferenceWorker:
    """Build the tick-to-order pipeline without starting its processing loop."""
    pipeline_queue = queue if queue is not None else RedisQueue(
        settings.redis_host, settings.redis_port
    )
    manager = build_order_manager(settings, enforce_market_hours=enforce_market_hours)
    router = build_signal_router(settings, manager, quantity, on_result)
    return InferenceWorker(pipeline_queue, predictor, router.route,
                            cursor_store=manager.repository,
                            cursor_name=getattr(pipeline_queue, "stream", "stock:ticks"))
```

```python
def build_runtime(settings: Settings, predictor: SignalPredictor,
                  queue: TickQueue | None = None, quantity: Any = 1,
                  on_result: Any = None, poll_interval: float = 1.0,
                  reconciler: OrderReconciler | None = None,
                  metrics: RuntimeMetrics | None = None,
                  on_error: Any = None, enforce_market_hours: bool = True) -> TradingRuntime:
    """Build a stoppable runtime around the configured trading pipeline."""
    worker = build_pipeline(settings, predictor, queue, quantity, on_result,
                            enforce_market_hours=enforce_market_hours)
    active_reconciler = reconciler if reconciler is not None else build_reconciler(settings)
    error_handler = on_error
    if error_handler is None and settings.telegram_enabled:
        error_handler = TelegramNotifier(settings.telegram_token, settings.telegram_chat_id)
    return TradingRuntime(
        worker, reconciler=active_reconciler, poll_interval=poll_interval,
        metrics=metrics,
        on_error=error_handler,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_application.py -v`
Expected: PASS (all tests, including the 2 new ones)

- [ ] **Step 5: Run the full suite to confirm no regressions**

Run: `python -m pytest -q`
Expected: PASS, no failures

- [ ] **Step 6: Commit**

```bash
git add src/application.py tests/test_application.py
git commit -m "feat: add enforce_market_hours bypass for off-hours tick replay"
```

---

## Task 4: Wire `--record`/`--replay` into `src/main.py`

**Files:**
- Modify: `src/main.py:1-176`
- Modify: `tests/test_main.py`

**Interfaces:**
- Consumes: `RecordingQueue(inner, path)` (Task 1), `replay_ticks(path, queue, stop_event)` (Task 2), `build_runtime(..., enforce_market_hours=...)` (Task 3).
- Produces: `build_parser()` gains `--record` and `--replay` arguments; `main()` rejects both being set; `_run_trading_loop` gains an `enforce_market_hours` parameter.

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/test_main.py
import json

import pytest

from src.main import build_parser, main


def test_build_parser_accepts_record_and_replay_flags():
    args = build_parser().parse_args(["005930", "--record", "ticks.jsonl"])
    assert args.record == "ticks.jsonl"
    assert args.replay is None

    args = build_parser().parse_args(["005930", "--replay", "ticks.jsonl"])
    assert args.replay == "ticks.jsonl"
    assert args.record is None


def test_main_rejects_record_and_replay_together(tmp_path, monkeypatch):
    monkeypatch.setenv("KIS_APPKEY", "key")
    monkeypatch.setenv("KIS_APPSECRET", "secret")
    monkeypatch.setenv("PAPER_TRADING", "true")

    with pytest.raises(SystemExit, match="not both"):
        main(["005930", "--record", "a.jsonl", "--replay", "b.jsonl"])


def test_main_replay_mode_runs_without_kis_credentials(tmp_path, monkeypatch):
    replay_path = tmp_path / "ticks.jsonl"
    replay_path.write_text(
        json.dumps({"ts": 1.0, "payload": {
            "symbol": "005930", "price": 70000, "volume": 10,
        }}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("KIS_APPKEY", "")
    monkeypatch.setenv("KIS_APPSECRET", "")
    monkeypatch.setenv("PAPER_TRADING", "true")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "trades.sqlite3"))

    class FakeQueue:
        def __init__(self, *args, **kwargs):
            pass

        def publish(self, message):
            return "1-0"

        def read(self, last_id="0-0", count=10):
            return []

    monkeypatch.setattr("src.main.RedisQueue", FakeQueue)

    result = main(["005930", "--replay", str(replay_path), "--status-interval", "0"])

    assert result == 0
```

(This test exercises the real `_run_trading_loop`/`build_runtime` against `FakeQueue`, so it doubles as an end-to-end check that `--replay` runs to completion without touching Redis, a KIS websocket, or a real clock check blocking the order.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_main.py -k "record_and_replay or accepts_record or replay_mode" -v`
Expected: FAIL — `build_parser` has no `--record`/`--replay` yet, `main` doesn't reject the combination.

- [ ] **Step 3: Write the implementation**

Modify `src/main.py`:

```python
from src.queue.recording_queue import RecordingQueue
from src.replay import replay_ticks
```

(add alongside the existing imports at the top, after `from src.queue.redis_queue import RedisQueue`)

Change `_run_trading_loop` to accept and forward the flag:

```python
def _run_trading_loop(settings: Settings, queue: RedisQueue, metrics: RuntimeMetrics,
                       stop_event: threading.Event, poll_interval: float, quantity: int,
                       enforce_market_hours: bool = True) -> None:
    predictor = MovingAverageStrategy()
    runtime = build_runtime(
        settings, predictor, queue=queue, quantity=quantity,
        on_result=_log_signal_result, metrics=metrics, poll_interval=poll_interval,
        enforce_market_hours=enforce_market_hours,
    )
    try:
        cycles = runtime.run(stop_event, count=10)
        logger.info("trading loop stopped after %d cycles", cycles)
    except Exception:
        logger.exception("trading loop crashed")
    finally:
        stop_event.set()
```

Add a replay-mode collector coroutine, next to `_run_collector`:

```python
async def _run_replay(path: str, queue: RedisQueue, stop_event: threading.Event) -> None:
    try:
        await replay_ticks(path, queue, stop_event)
    finally:
        # Replay finished (or hit an error) — nothing is publishing ticks
        # anymore, so the trading loop must stop instead of polling forever.
        stop_event.set()
```

Add the CLI flags in `build_parser`:

```python
    parser.add_argument("--record", default=None,
                        help="append every published tick to this JSONL file for later replay")
    parser.add_argument("--replay", default=None,
                        help="replay ticks from this JSONL file instead of the live KIS websocket")
```

Update `main()`:

```python
def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.record and args.replay:
        raise SystemExit("--record and --replay cannot be used together, pass not both")

    settings = Settings()
    if args.replay is None:
        if not settings.kis_appkey.strip() or not settings.kis_appsecret.strip():
            raise SystemExit("KIS_APPKEY and KIS_APPSECRET are required to start the tick collector")
        if not settings.is_paper:
            settings.validate_for_live()

    raw_queue = RedisQueue(settings.redis_host, settings.redis_port)
    queue = RecordingQueue(raw_queue, args.record) if args.record else raw_queue
    metrics = RuntimeMetrics()
    stop_event = threading.Event()

    def _handle_signal(signum: int, _frame: object) -> None:
        logger.info("received signal %s, shutting down", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    threads = [threading.Thread(
        target=_run_trading_loop,
        args=(settings, queue, metrics, stop_event, args.poll_interval, args.quantity),
        kwargs={"enforce_market_hours": args.replay is None},
        name="trading-loop", daemon=True,
    )]
    if args.health_port is not None:
        threads.append(threading.Thread(
            target=_run_health_server,
            args=(settings, queue, metrics, args.health_port, stop_event),
            name="health-server", daemon=True,
        ))
    if args.status_interval > 0:
        threads.append(threading.Thread(
            target=_run_status_logger,
            args=(metrics, stop_event, args.status_interval),
            name="status-logger", daemon=True,
        ))
    for thread in threads:
        thread.start()

    logger.info("tick collector starting for symbols=%s paper=%s replay=%s",
                args.symbols, settings.is_paper, args.replay is not None)
    try:
        if args.replay is not None:
            asyncio.run(_run_replay(args.replay, queue, stop_event))
        else:
            asyncio.run(_run_collector(settings, args.symbols, queue, stop_event))
    finally:
        stop_event.set()
        for thread in threads:
            thread.join(timeout=10)

    return 0
```

Note: `raw_queue`/`queue` here mirrors the existing `queue = RedisQueue(...)` line it replaces — the only change is the optional `RecordingQueue` wrap and the `--replay` branch calling `_run_replay` instead of `_run_collector`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_main.py -v`
Expected: PASS (all tests, including the 3 new ones)

- [ ] **Step 5: Run the full suite to confirm no regressions**

Run: `python -m pytest -q`
Expected: PASS, no failures

- [ ] **Step 6: Manual smoke test (weekday, real KIS) — record**

Run (during market hours):
```powershell
python -m src.main 005930 --record ticks_smoke.jsonl --status-interval 5
```
Let it run ~30 seconds, Ctrl+C. Expected: process exits cleanly, `ticks_smoke.jsonl` exists and has at least one JSON line with `"ts"` and `"payload"` keys.

- [ ] **Step 7: Manual smoke test — replay**

Run (any time, using the file from Step 6):
```powershell
python -m src.main 005930 --replay ticks_smoke.jsonl --status-interval 5
```
Expected: process runs without requiring valid KIS credentials, replays the recorded ticks, logs signal activity via `_log_signal_result` if any tick crosses the strategy's threshold, and exits (return code 0) once the file is exhausted.

- [ ] **Step 8: Commit**

```bash
git add src/main.py tests/test_main.py
git commit -m "feat: add --record/--replay flags to observe the pipeline outside market hours"
```

---

## Task 5: Update development docs

**Files:**
- Modify: `development.md`

**Interfaces:**
- Consumes: nothing (documentation only).
- Produces: nothing consumed by other tasks — this is the last task.

- [ ] **Step 1: Add a short section to `development.md`**

Find the section documenting `python -m src.main` usage (added in the commit that introduced `src/main.py`) and add immediately after it:

```markdown
### Off-hours observation (record/replay)

Market data only flows during weekday KRX hours (09:00-15:30 KST). To observe
the pipeline at night or on weekends, record real ticks during market hours
and replay them later at their original pace:

```powershell
# During market hours: trade normally AND record every tick to a file
python -m src.main 005930 --record ticks_20260907.jsonl

# Later (any time): replay those ticks through the same pipeline
python -m src.main 005930 --replay ticks_20260907.jsonl
```

`--replay` does not require valid KIS credentials (no live connection is
made) and does not apply the wall-clock market-hours check — the replayed
ticks are trusted to represent an already-valid trading session. `--record`
and `--replay` cannot be combined.
```

- [ ] **Step 2: Commit**

```bash
git add development.md
git commit -m "docs: document --record/--replay for off-hours pipeline observation"
```

---

## Self-Review Notes

- **Spec coverage:** `RecordingQueue` (spec §1) → Task 1. `replay_ticks` (spec §2) → Task 2. CLI flags (spec §3) → Task 4. Market-hours bypass (spec §4) → Task 3. Error handling (record-write failure logged, replay parse failure raises, mutually-exclusive flags rejected) → Tasks 1, 2, 4. Usage example → Task 5.
- **Placeholder scan:** no TBD/TODO; all steps contain runnable code.
- **Type consistency:** `RecordingQueue.publish` and `replay_ticks`'s `queue` argument both use the `publish(message: dict) -> str` contract from `RedisQueue` (`src/queue/redis_queue.py:36`) — no mismatch. `enforce_market_hours: bool = True` has the identical name and default across `build_order_manager`, `build_pipeline`, `build_runtime`, and `_run_trading_loop`.
