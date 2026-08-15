# Stock Trading Bot with Deep Learning

한국투자증권(KIS) API를 사용하는 비동기 주식 자동매매 시스템입니다. 실시간 시세 수집, 모델 추론, 리스크 검증, 주문 실행을 분리해 운영합니다.

## Project Structure
- `docs/`: System architecture and documentation.
- `src/`: Core source code.
    - `api/`: KIS API wrapper and WebSocket handler.
    - `inference/`: Async deep learning inference worker.
    - `engine/`: Tick processor and order manager.
- `models/`: Pre-trained model files.
- `dashboard/`: Monitoring UI.

현재 구현된 기반 모듈:
- `src/models.py`: tick, signal, order, trade log 데이터 계약
- `src/database/sqlite.py`: SQLite 거래 로그 저장소
- `src/engine/risk.py`: 신호 강도, 주문 금액, 일일 손실 한도 검증
- `src/engine/order_manager.py`: 모의주문 기본 주문 관리자
- `src/queue/redis_queue.py`: Redis Streams 메시지 큐 어댑터

## Getting Started
1. Python 3.11 이상을 설치합니다.
2. 의존성을 설치합니다: `pip install -r requirements.txt`
3. `.env.example`을 `.env`로 복사합니다.
4. 초기 개발 단계에서는 `PAPER_TRADING=true`를 유지합니다.
5. 테스트를 실행합니다: `pytest -q`
6. Redis Streams를 사용할 때만 Redis 서버를 실행합니다.

실제 KIS 주문 어댑터와 딥러닝 추론 워커는 다음 단계에서 연결합니다. 실거래 전에는 모의투자 API, 주문 중복 방지, 잔고/보유수량 검증, 장 운영시간 검증을 반드시 추가해야 합니다.
