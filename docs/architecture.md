# System Architecture: Deep Learning Based Async Trading System

## 1. Overview
This system is designed to handle high-frequency tick data processing and compute-intensive deep learning inference asynchronously. By decoupling I/O-bound tasks from compute-bound tasks, we ensure minimal latency in trade execution while utilizing complex models for signal generation.

## 2. High-Level Architecture
```text
[ Market Data (KIS WebSocket) ]
           |
           v
[ Engine: Tick Processor (I/O Bound) ] <-----> [ Queue: Redis/RabbitMQ ]
           |                                          ^
           | (Publish Tick Data)                      | (Publish Signal)
           v                                          |
[ Inference: DL Engine (Compute Bound) ] -------------+
           |
           v (Execute Signal)
[ Engine: Order Manager ]
           |
           v
[ Broker API (KIS API) ]
```

### 2.1 Daily Symbol Selection (pre-market)
```text
[ Task Scheduler 08:55 ] -> scripts/record_market_open.ps1
           |
           v
[ src/screener.py ] --GET volume-rank (FHPST01710000)--> [ KIS REST ]
           |  filter: no ETF/ETN/preferred/managed, price >= 1000,
           |          1% <= |change| <= 15%, top 5 by trading value
           v
  symbols = 005930 (fixed) + picks   (fallback: 005930 only on any failure)
           |  sleep 65s  (KIS token: 1 issue / minute / app key)
           v
[ src.main <symbols> --record ticks_YYYYMMDD.jsonl ]  -> pipeline above
```
The screener and the collector are separate processes and each issues its
own KIS access token, so they are spaced apart to stay under the token rate
limit (`EGW00133`). Symbol selection is decoupled from the strategy: the
strategy sees whatever symbols the collector was started with.

### 2.2 Offline Training Path
```text
data/ticks/ticks_YYYYMMDD.jsonl  (one file = one recording day)
           |  per-symbol series (never interleaved)
           v
[ src/training/train.py ]
   - day-level holdout: newest day(s) validate, older days train
     (single file falls back to a within-day chronological split)
   - label thresholds = train-side return quantiles (30% / 70%);
     strict comparison, so zero return is HOLD
   - reports val_accuracy with val label counts and the majority-class
     baseline (a model only counts if it clearly beats the baseline)
           v
models/*.pt (gitignored)  ->  src/strategies/lstm_strategy.py (same
                              normalize_window as training, no drift)
```

## 3. Pipeline Segregation
- **I/O Bound Pipeline**: Handles WebSocket connections, REST API calls, and basic data validation.
- **Compute Bound Pipeline**: Dedicated worker processes that consume tick data from the queue, perform feature engineering, and run model inference.
- **Data environment note**: `KIS_BASE_URL` points at the real KIS server (market data and ranking queries); orders are recorded locally as `simulated` and never sent to KIS while `PAPER_TRADING=true`. Whether ranking APIs work on the KIS paper server (`openapivts`) is unverified.

## 4. Technology Stack
- **Language**: Python 3.x
- **Deep Learning**: PyTorch / TensorFlow
- **Async Communication**: Redis (Pub/Sub or Streams)
- **API**: 한국투자증권 (KIS) KOREA INVESTMENT & SECURITIES
- **Database**: SQLite (Trade logs) / Parquet (Feature store)
- **Monitoring**: React + FastAPI

## 5. Database Schema (Initial)
- `trade_logs`: id, timestamp, symbol, side, quantity, price, strategy_id, signal_strength
- `model_metadata`: model_id, version, training_date, performance_metrics
