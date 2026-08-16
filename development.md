# 개발 현황 및 실행 가이드

작성 기준: 2026-08-16

## 1. 현재 개발 현황

현재 시스템은 KIS 기반 비동기 주식 자동매매의 paper-trading 파이프라인과
live 전환을 위한 안전장치를 구현한 상태입니다.

현재 전체 진행률은 약 99%로 추정합니다. 이 수치는 저장소에 정의된 핵심
컴포넌트의 구현·테스트 완료 기준이며, 실제 KIS 계정과 운영 인프라를
사용한 외부 검증은 별도 단계입니다.

### 구현 완료 항목

- typed market tick, signal, order, trade-log 모델
- UTC timezone-aware timestamp 정규화
- SQLite trade log 저장소
- paper portfolio 현금·보유수량 검증 및 재시작 복원
- 신호 강도, 주문 금액, 일일 손실 위험 게이트
- 시장시간·휴일 주문 차단
- paper/live 주문 manager 분리
- KIS REST 인증 및 현재가 조회
- KIS 국내주식 지정가 주문 adapter
- KIS 주문 상태 조회 및 페이지네이션
- 주문 상태 재조정 및 unknown order 차단
- KIS WebSocket approval, 구독, tick parsing
- WebSocket 자동 재연결 및 exponential backoff
- Redis Streams publish/read adapter
- inference worker 및 moving-average baseline strategy
- auto/manual automation mode
- runtime cycle 오류 격리 및 재시작 없는 loop 운영
- runtime metrics 및 `/metrics` endpoint
- `/health` readiness endpoint
- Telegram runtime error notification adapter
- `.env` 자동 로딩
- 배포 전 설정 검증 CLI
- KIS 인증 및 read-only 현재가 smoke command

### 주요 실행 흐름

```text
KIS WebSocket
    -> Redis Streams
    -> InferenceWorker
    -> SignalOrderRouter
    -> RiskGate / MarketHours / PortfolioState
    -> OrderManager
    -> SQLite
```

live mode에서는 OrderManager가 KIS 주문 executor를 사용하고, runtime cycle에서
KIS 주문 상태 reconciliation을 수행합니다. paper mode에서는 broker 주문을
호출하지 않고 simulated trade를 SQLite에 기록합니다.

## 2. 개발 환경 준비

### 요구 사항

- Python 3.11 이상
- Redis 6 이상 권장
- KIS Open API 계정 및 app key/secret
- paper trading 개발 시에도 Redis가 필요합니다. 단위 테스트는 Redis 없이 실행됩니다.

### 설치

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

환경 파일을 생성합니다.

```powershell
Copy-Item .env.example .env
```

`.env`는 애플리케이션 시작 시 자동으로 로드됩니다. 운영체제에 명시적으로
설정한 환경변수가 `.env`보다 우선합니다.

## 3. 주요 환경변수

### KIS

```text
KIS_BASE_URL=https://openapi.koreainvestment.com:9443
KIS_CANO=8자리 계좌번호
KIS_ACNT_PRDT_CD=01
KIS_APPKEY=...
KIS_APPSECRET=...
```

live 검증 시 계좌번호는 8자리 숫자, 상품코드는 2자리 숫자, base URL은
HTTPS여야 합니다.

### 안전 및 자동화

```text
PAPER_TRADING=true
AUTOMATION_MODE=manual
MIN_SIGNAL_STRENGTH=0.60
MAX_ORDER_VALUE=1000000
MAX_DAILY_LOSS=100000
PAPER_STARTING_CASH=10000000
KIS_ORDER_LOOKBACK_DAYS=1
MARKET_HOLIDAYS=2026-01-01,2026-03-02
```

- 개발 기본값은 `PAPER_TRADING=true`입니다.
- `AUTOMATION_MODE=manual`이면 신호가 주문으로 전환되지 않습니다.
- `PAPER_STARTING_CASH`는 paper portfolio 복원 시 시작 현금입니다.
- `KIS_ORDER_LOOKBACK_DAYS`는 live reconciliation의 조회 calendar day 범위입니다.
- 위험 한도 값은 음수가 될 수 없고 신호 강도는 0~1 범위여야 합니다.

### Redis 및 SQLite

```text
REDIS_HOST=localhost
REDIS_PORT=6379
DATABASE_PATH=./data/trading.sqlite3
```

### Telegram 알림(선택)

```text
TELEGRAM_TOKEN=...
TELEGRAM_CHAT_ID=...
```

두 값을 모두 설정하면 runtime 오류 callback이 Telegram notifier로 자동
연결됩니다. 하나만 설정하면 설정 오류로 처리됩니다.

## 4. 검증 명령

전체 테스트:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

현재 기준 테스트 수는 122개입니다.

설정만 검증하는 명령은 network request를 수행하지 않습니다.

```powershell
python -m src.cli validate-config
python -m src.cli validate-config --live
```

유효한 KIS credentials가 있을 때만 다음 명령을 실행합니다.

```powershell
# access token만 확인하며 주문하지 않음
python -m src.cli check-kis-auth

# 현재가만 조회하며 주문하지 않음
python -m src.cli check-kis-price 005930
```

## 5. 애플리케이션 조립 및 실행

`src/main.py`가 틱 수집기(KIS WebSocket → Redis)와 매매 루프
(`TradingRuntime`)를 한 프로세스로 묶어 실행합니다. 하나가 죽으면(예: 웹소켓
재연결 한도 초과) 다른 하나도 함께 정지하도록 되어 있어, 절반만 살아있는
상태로 조용히 방치되지 않습니다.

```powershell
# 종목 코드는 6자리, 여러 개 지정 가능
python -m src.main 005930 000660 --quantity 1 --poll-interval 1.0 --health-port 8080
```

- `--quantity`: 종목 구분 없이 신호 1건당 매매 수량 (기본 1주). 종목별로
  다르게 주려면 아직 코드 수정이 필요합니다(`SignalOrderRouter`는 이를
  지원하지만 `src/main.py`는 아직 단일 값만 CLI로 받습니다).
- `--poll-interval`: 매매 루프 주기(초).
- `--health-port`: 지정하면 `/health`, `/metrics`를 해당 포트에 띄웁니다.
  생략하면 health 서버 없이 수집기+매매 루프만 돕니다.
- `Ctrl+C`(SIGINT) 또는 SIGTERM으로 정상 종료됩니다.

전략(predictor)은 현재 `src/strategies/moving_average.py`의
`MovingAverageStrategy`로 고정되어 있습니다. 딥러닝 모델을 붙이려면
`src/main.py`의 `_run_trading_loop`에서 predictor 생성 부분만 교체하면
됩니다.

프로그램 안에서 직접 조립하고 싶다면 다음과 같이 API를 사용할 수 있습니다:

```python
from src.application import build_runtime
from src.config import Settings
from src.monitoring.metrics import RuntimeMetrics
from threading import Event

settings = Settings()
metrics = RuntimeMetrics()

runtime = build_runtime(
    settings,
    predictor=my_predictor,
    metrics=metrics,
    poll_interval=1.0,
)

runtime.run(Event(), count=10)
```

이 경우에도 `RedisQueue`를 queue로 주입하고, `KISWebSocketClient`의
`stream_to_queue()`를 별도 async task/process로 실행해야 합니다.

## 6. Health 및 Metrics

`build_health_app(settings, queue, metrics)`로 FastAPI 앱을 만들 수 있습니다.

- `GET /health`: SQLite와 Redis readiness를 확인합니다. 의존성 실패 시 503을 반환합니다.
- `GET /metrics`: runtime cycle, signal, 오류, reconciliation counters를 반환합니다.

예시:

```python
from src.application import build_health_app
from src.config import Settings

app = build_health_app(Settings(), queue=redis_queue, metrics=metrics)
```

FastAPI/uvicorn으로 외부에 노출할 때는 인증·네트워크 접근제어를 별도로
설정해야 합니다.

## 7. Live 전환 전 안전 절차

1. `PAPER_TRADING=true`로 전체 테스트를 실행합니다.
2. `AUTOMATION_MODE=manual`로 pipeline 연결을 확인합니다.
3. `python -m src.cli validate-config --live`를 실행합니다.
4. `check-kis-auth`로 access token 발급을 확인합니다.
5. `check-kis-price 005930`으로 read-only 시세 조회를 확인합니다.
6. 소액·제한된 paper 환경에서 WebSocket, Redis, runtime, `/health`, `/metrics`를 확인합니다.
7. Telegram 등 오류 알림 수신을 확인합니다.
8. 실계좌 전환 시 별도 승인 후 `PAPER_TRADING=false`로 변경합니다.

`check-kis-auth`와 `check-kis-price`는 주문을 제출하지 않지만, live credentials를
사용하므로 실행 로그와 token 취급에 주의해야 합니다.

## 8. 아직 외부 환경에서 해야 하는 작업

- 실제 KIS paper 계정으로 WebSocket 연결·재연결 확인
- 실제 Redis 서버에서 stream publish/read 확인
- KIS paper 주문의 submitted/filled/cancelled/rejected lifecycle 확인
- 장중·장외·휴일 및 네트워크 단절 시 runtime 동작 확인
- 배포 프로세스(supervisor/systemd/Docker 등)와 secret 관리 확정
- 실계좌 전환 전 주문 금액·종목·계좌 권한 최종 확인

현재 코드와 테스트는 이 외부 검증을 수행할 수 있도록 adapter, smoke command,
오류 처리, metrics, health endpoint를 제공합니다. credentials가 없는 환경에서는
위 smoke command를 실행하지 말고 단위 테스트와 `validate-config`까지만 실행합니다.
