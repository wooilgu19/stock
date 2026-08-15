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

## 3. Pipeline Segregation
- **I/O Bound Pipeline**: Handles WebSocket connections, REST API calls, and basic data validation.
- **Compute Bound Pipeline**: Dedicated worker processes that consume tick data from the queue, perform feature engineering, and run model inference.

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
