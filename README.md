# Stock Trading Bot with Deep Learning

An asynchronous stock auto-trading system using the Korea Investment & Securities (KIS) API. Market data, model inference, risk checks, and order execution are separated into independent components.

## Current Components

- `src/models.py`: Typed tick, signal, order, and trade-log contracts.
- `src/database/sqlite.py`: SQLite persistence for trade logs.
- `src/engine/risk.py`: Signal, order-value, and daily-loss checks.
- `src/engine/order_manager.py`: Paper-trading-first order orchestration.
- `src/api/kis_rest.py`: KIS authentication and domestic stock price client.
- `src/api/kis_websocket.py`: KIS real-time execution-price WebSocket client.
- `src/queue/redis_queue.py`: Redis Streams adapter.

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
6. Run tests: `pytest -q`

## Safety Notes

Live order submission is not connected yet. Keep paper trading enabled until the KIS order adapter, duplicate-order protection, balance and position checks, market-hours checks, and operational monitoring are implemented and verified.
