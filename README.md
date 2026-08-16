# Stock Trading Bot with Deep Learning

An asynchronous stock auto-trading system using the Korea Investment & Securities (KIS) API. Market data, model inference, risk checks, and order execution are separated into independent components.

## Current Components

- `src/models.py`: Typed tick, signal, order, and trade-log contracts.
- `src/database/sqlite.py`: SQLite persistence for trade logs.
- `src/engine/risk.py`: Signal, order-value, and daily-loss checks.
- `src/engine/order_manager.py`: Paper-trading-first order orchestration.
- `src/engine/market_hours.py`: Basic KRX weekday/session-hours guard.
- `src/engine/portfolio.py`: Paper-trading cash and position checks.

`PortfolioState.from_repository(...)` can restore paper cash and positions from
persisted simulated/filled trades after a process restart.

`MarketHours(holidays={...})` accepts exchange holiday dates and blocks orders
on those dates. The holiday set is intentionally supplied by the caller so a
future KRX calendar provider can be added without changing order execution.

Set `MARKET_HOLIDAYS` as a comma-separated ISO-date list, then build the guard
from application settings, for example:

```text
MARKET_HOLIDAYS=2026-01-01,2026-03-02
```

```python
market_hours = MarketHours.from_settings(settings)
```

Live reconciliation checks recent broker order history. Set
`KIS_ORDER_LOOKBACK_DAYS` to control how many calendar days are queried
(default: `1`).
- `src/engine/signal_router.py`: Converts BUY/SELL signals into risk-checked orders; HOLD signals are ignored.
- `src/api/kis_rest.py`: KIS authentication, price client, and explicit
  domestic cash-order executor (limit orders only), plus recent order-status
  provider for reconciliation, including configurable recent-day lookback.
- `src/application.py`: Builds a paper-safe or credential-validated live
  order manager without making network calls during startup.
- `src/monitoring/health.py`: Non-mutating database and queue readiness checks.
- `src/api/health.py`: FastAPI `/health` endpoint returning 503 on dependency
  failure.
- `src/engine/reconciliation.py`: Applies broker lifecycle updates only to
  known locally submitted orders.
- `build_health_app(settings)` in `src/application.py` wires the endpoint to
  configured SQLite and Redis dependencies without probing them at startup.
- `build_signal_router(settings, order_manager, ...)` applies
  `AUTOMATION_MODE`; manual mode drops actionable signals before order creation.
- `build_pipeline(settings, predictor, ...)` connects Redis ticks, inference,
  automation mode, risk checks, and order persistence.
- `src/runtime.py`: Runs the assembled pipeline in single-cycle or stoppable
  loop mode.
- `build_runtime(settings, predictor, ...)` creates the configured runtime
  without starting it and can run reconciliation in the same cycle.
- `build_reconciler(settings)` automatically enables KIS status reconciliation
  only for validated live settings; paper mode remains local-only.
- `src/api/kis_websocket.py`: KIS real-time execution-price WebSocket client.
- `src/queue/redis_queue.py`: Redis Streams adapter.
- `src/inference/worker.py`: Redis tick consumer and signal dispatcher.
- `src/strategies/moving_average.py`: Deterministic baseline strategy for pipeline validation.

The current paper-trading pipeline can be connected as:

```text
KIS WebSocket -> RedisQueue -> InferenceWorker -> SignalOrderRouter -> OrderManager -> SQLite
```

## Development Setup

1. Install Python 3.11 or newer.
2. Create and activate the project environment:

   ```powershell
   py -3 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. Install dependencies: `python -m pip install -r requirements.txt`
4. Copy `.env.example` to `.env` and fill in credentials.
5. Keep `PAPER_TRADING=true` during development.
6. Set `AUTOMATION_MODE=auto` to enable automatic signal-to-order processing.
   This setting does not enable live trading; `PAPER_TRADING` remains an
   independent safety switch.
6. Run tests: `pytest -q`

## Safety Notes

Live order submission is intentionally blocked unless an explicit broker
executor is injected into `OrderManager`. The manager never records a live
order as `submitted` before that executor confirms acceptance. Keep paper
trading enabled until the KIS order adapter and operational monitoring are
implemented and verified.
