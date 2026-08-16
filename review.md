# 서브에이전트 통합 개발 검토 (2026-08-16)

5개 서브에이전트(시스템 아키텍트, 퀀트&피처 엔지니어, 리스크 게이트, 성능&인프라 프로파일러, QA&백테스팅 검수자)가 각자 영역에서 현재 `src/` 코드를 read-only로 검토한 결과를 취합했다. 여러 에이전트가 독립적으로 동일한 근본 원인을 지목한 항목은 통합 표기했다.

## 🔴 Critical — 즉시 조치

### 1. 일일 손실 한도(Kill-Switch)가 항상 0 → 사실상 미작동
(시스템 아키텍트 / 리스크 게이트 / QA 3개 에이전트 동일 지적)

- `src/database/sqlite.py:69` `daily_realized_loss()`가 `status = 'loss'` 행만 집계하는데, 실제 저장 경로(`order_manager.py:71`)는 `simulated/submitted/filled/cancelled/rejected`만 기록 — `'loss'`는 아무도 쓰지 않음.
- 결과: `src/engine/risk.py:31`의 `daily_loss >= max_daily_loss`는 항상 `0 >= N` → **손실이 얼마든 주문이 무한히 나간다.**
- `tests/test_trading_core.py:12`가 `status="loss"` 행을 직접 INSERT해서 테스트를 통과시키고 있어, 프로덕션 경로가 깨진 걸 테스트가 가리고 있음(QA 지적).
- **개선안**: 체결 기준 실현손익 집계로 쿼리 교체 (매도 체결가 - 매수 원가). 최소 diff로 가능.

### 2. Kill-Switch 자체가 존재하지 않음
- 저장소 전체에 연속 손실/API 오류율/이상 시세에 반응하는 서킷브레이커가 없음(리스크 게이트).
- `runtime.py:55-66`은 예외를 로그·알림만 하고 다음 사이클을 그대로 진행.
- `signal_router.py:35`의 `automation_enabled`는 생성자 고정값 — 런타임 차단 수단이 아님.
- **개선안**: `OrderManager.submit` 단일 경로 최상단에 상태 플래그 기반 거부 게이트 추가. 해제는 수동만.

### 3. 워커 재시작 시 Redis 스트림 전체 리플레이 → 과거 틱으로 실주문
(시스템 아키텍트 / 퀀트&피처 엔지니어 동일 지적)

- `src/inference/worker.py:34` `last_id`가 프로세스 메모리에만 존재, `"0-0"`으로 시작.
- 재시작하면 그날 틱을 전부 재추론 → 과거 가격으로 MA 크로스 재현 가능.
- `signal_router.py:58-61`의 `client_order_id`가 `signal.timestamp`(추론 시각) 기반이라 리플레이마다 키가 달라져 **중복 주문 방지도 무력화**.
- **개선안**: `last_id`를 SQLite에 영속화(consumer group 도입은 YAGNI). `client_order_id`를 `tick.timestamp` 기반으로 변경.

### 4. 주문 제출과 DB 기록 사이 크래시 창 (고아 주문)
- `src/engine/order_manager.py:63-74` — 브로커에 주문 접수 후 `repository.save()` 사이 크래시 시, 로컬엔 기록이 없어 `OrderReconciler`가 이 주문을 `ignored`로 버림(`reconciliation.py:31-33`) → 포지션 영구 어긋남.
- **개선안**: `executor.submit()` 이전에 `status='pending'` 행을 먼저 저장(write-ahead), 성공 시 `submitted`로 갱신. `pending_order_ids()`가 `pending`도 포함하도록 확장.

### 5. 백테스트 엔진 자체가 없음
- `tests/`, `src/` 어디에도 틱 리플레이/백테스트 하네스가 없음. 슬리피지·수수료·체결 지연 모델 전무(QA).
- 페이퍼 모드는 신호가 나면 즉시 신호 가격 그대로 전량 체결로 기록 → 검증 성적이 구조적으로 낙관 편향.
- **개선안**: 최소 틱 리플레이 테스트 1개 + 페이퍼 체결에 슬리피지/수수료 파라미터(기본 0) 도입.

## 🟠 High

| # | 문제 | 위치 | 담당 |
|---|---|---|---|
| 6 | 배치 처리 중 예외 시 틱 이중 반영 → 이동평균 왜곡 | `worker.py:40-45`, `runtime.py:47` | 퀀트/아키텍처 |
| 7 | 틱 타임스탬프 폐기 — 라이브(처리시각) vs 백테스트/학습(틱시각) 시간축 불일치 | `worker.py:23`, `moving_average.py:26,42`, `models.py:58` | 퀀트 |
| 8 | Rate Limit 미구현 — KIS 초당 20건 제한 초과 시 예외로 시그널 유실 | `kis_rest.py:48-63` | 리스크 |
| 9 | 미체결 타임아웃 없음 — `submitted` 무기한 보유, 자동 취소 없음 | `sqlite.py:84`, `reconciliation.py` | 리스크 |
| 10 | 분할체결 FSM 누락 — 제출 즉시 전량체결로 포트폴리오 반영, 부분/거부 시 롤백 없음 | `kis_rest.py:264-266`, `order_manager.py:75-76` | 리스크/QA |
| 11 | WebSocket 이벤트 루프 블로킹 — 동기 `requests.post`(최대 10초)가 async 함수 안에서 직접 호출 | `kis_websocket.py:118` | 성능 |
| 12 | 틱 핫패스에서 동기 Redis 호출 — `xadd`가 루프를 블로킹, 백프레셔 없음 | `kis_websocket.py:136`, `redis_queue.py:33` | 성능 |
| 13 | Redis 스트림 무한 증가(메모리 릭) — `maxlen` 트리밍 없음 | `redis_queue.py:33` | 성능/아키텍처 |
| 14 | 예외 시나리오 테스트 공백 — 주문 거부/부분체결/Rate Limit/포이즌 메시지 전부 무테스트 | 전역 | QA |
| 15 | WebSocket 재연결 카운터가 리셋되지 않음 — 하루 3회 재연결 후 영구 종료 | `kis_websocket.py:115` | 아키텍처 |

## 🟡 Medium

- 재시작 시 리스크 한도 우회: `filled/simulated`만 집계해 미체결 매수 현금이 복원됨 (`sqlite.py:112`)
- 제출 중 네트워크 타임아웃 = 브로커는 접수, 로컬 미기록 → 재시도 시 이중 주문 가능성 (`kis_rest.py:139`)
- `OrderManager.submit`에 원자성 없음 — check-then-act, 락 없음, 동시 호출 시 한도 우회 가능
- 리컨실리에이션 동기 페이지네이션이 최악의 경우 사이클을 수백 초 잡아먹어 워커 처리 지연 (`kis_rest.py:220-241`)
- 포이즌 메시지 무한 재처리 — `on_tick`/`on_signal` 예외 시 `last_id` 미전진, 같은 메시지 영원히 재시도 (`worker.py:40-43`)
- 심볼 dict 무제한 증가 — 오타/해지 심볼도 영구 상주 (`moving_average.py:16`)
- 라이브 중복 주문 방지 실패 — `has_order_id`가 `broker_order_id`(KIS ODNO)를 조회, 재시작 후 차단 실패
- 프로세스 격리 사실상 없음 — 추론/주문/정합성이 한 스레드 순차 실행, `TradeRepository` 3곳에서 각각 생성돼 향후 프로세스 분리 시 `database is locked` 위험

## ✅ 잘 되어 있는 부분

- `client_order_id` 기반 멱등성, 라이브에서 executor 미설정 시 조용한 시뮬레이션 전락 방지 (`order_manager.py:56`)
- `update_order_status`의 `WHERE status='submitted'` 조건부 갱신 — 터미널 상태 되돌림 방지, 경합 안전
- 현재 틱만으로 MA 계산 — look-ahead bias 없음, 워밍업 전 HOLD 처리 정상
- `Tick`/`Signal` frozen dataclass + UTC 타임스탬프 정규화 일관
- `monitoring/metrics.py` — 순수 정수 카운터만 유지, 누수 위험 없음
- `KISRestClient` — Session 재사용, 토큰 캐시(1분 안전마진), 페이지네이션 무한루프 방어
- 라이브/페이퍼가 `OrderManager` 단일 경로 공유 (이중 구현 없음)
- `PortfolioState.from_repository`를 통한 재시작 시 포트폴리오 복원

## 우선순위 액션 (통합)

1. **`daily_realized_loss` 쿼리 수정 + Kill-Switch를 `OrderManager.submit` 단일 진입점에 배치** — 지금은 리스크 한도가 "있다고 믿는" 상태가 가장 위험.
2. **주문 write-ahead(제출 전 `pending` 기록) + 분할체결 FSM 추가** — 고아 주문·유령 포지션 제거.
3. **`last_id` SQLite 영속화 + `client_order_id`를 틱 시각 기반으로 변경** — 재시작 리플레이로 인한 중복 주문 차단.
4. **WebSocket/Redis 핫패스 async화 (`asyncio.to_thread` 또는 `redis.asyncio`) + `xadd maxlen` 추가** — 각 1~2줄, 이벤트 루프 블로킹과 메모리 릭 동시 해소.
5. **최소 틱 리플레이 백테스트 하네스 + 예외 시나리오 테스트(주문 거부/부분체결/포이즌 메시지) 추가** — 현재 테스트가 죽은 리스크 로직을 가리고 있었던 것과 같은 사고를 재발 방지.

---
*검토 담당: system-architect, quant-feature-engineer, risk-gate, perf-infra-profiler, qa-backtest-reviewer (병렬 read-only 검토, 코드 수정 없음)*

---

# 2차 재검토 (2026-08-16, 라운드 2)

동일한 5개 서브에이전트로 처음부터 다시 검토. 1차 지적 사항의 유효성을 재확인하고, 1차에서 놓친 신규 결함을 추가로 찾는 것이 목표. 일부 항목(Redis `xadd maxlen`, `asyncio.to_thread` 발행, `client_order_id` 틱시각 기반화)은 **1차 검토 이후 이미 반영되어 있음을 확인**했다.

## 🔴 Critical — 신규 발견

### 11. `attach_broker_order`가 `client_order_id` 없는 주문에서 조용히 실패 → 유령 주문
(리스크 게이트 / 시스템 아키텍트 중복 지적)

- `src/engine/order_manager.py:69-81` — `client_order_id`가 None이면 저장 행의 `client_order_id` 컬럼이 NULL로 들어가는데, `attach_broker_order`(`sqlite.py:146-153`)는 `WHERE client_order_id = ?`로 매칭 → **0행 매칭, 반환값도 무시됨**.
- 결과: 실제로는 체결된 주문이 로컬 DB엔 `broker_order_id='pending-...'` 상태로 영구 고정. `pending_order_ids()`가 이 가짜 id를 반환하고, `reconciliation.py:31`이 실체결 업데이트를 계속 `ignored` 처리 → 포지션·일일손실 미반영.
- **개선안**: 저장 시 `client_order_id`를 항상 채우도록 강제 + `attach_broker_order` 실패(0행) 시 실패 반환하고 즉시 halt+알림.

### 12. 커서(last_id)가 주문 라우팅 이전에 커밋됨 → 실패한 신호가 영구 소실
(퀀트&피처 / QA 중복 지적, QA가 재현 확인)

- `src/inference/worker.py:46-51` 순서가 `last_id 갱신 → 커서 저장 → on_signal(주문 라우팅)`.
- `on_signal`(=`router.route`, 실주문 제출 경로)이 예외를 던지면 — 특히 `signal_router.py:43`의 `_quantity_for`가 미설정 심볼에 `ValueError`를 던지는 것 하나만으로도 — 커서는 이미 영속화된 뒤라 **그 틱의 매매 시그널이 영구 소실**되고 재시도되지 않음.
- QA가 재현: 심볼 하나 미설정 상태로 배치를 흘리면 해당 배치 전체 틱이 조용히 사라짐.
- **개선안**: `on_signal` 성공 이후로 커서 저장을 이동. `_quantity_for`는 raise 대신 거부 결과 반환.

### 13. 시장시간 게이트가 "현재 시각"이 아니라 주문/틱 타임스탬프를 사용 → 장 마감 후 과거가로 주문 가능
(QA 신규 지적)

- `src/engine/order_manager.py:46`의 `is_open` 판정이 `order.timestamp`(=신호/틱 시각) 기준.
- 장애 복구로 Redis 백로그를 재생하면 **장 마감 후에도 과거 가격 기준으로 주문이 제출**될 수 있음. 백테스트 replay와 실거래가 같은 경로를 타는 데서 비롯된 구조적 결함.
- **개선안**: `is_open` 판정을 주입 가능한 `now()`로 분리하고, `order.timestamp`와 실제 현재 시각의 격차가 임계값(예: 5초)을 넘으면 거부.

### 14. `daily_realized_loss`의 legacy 폴백이 손실 한도를 다시 은폐
(QA가 실측 재현)

- `src/database/sqlite.py:112` `if not rows:` 폴백 — legacy 방식 단독일 땐 300.0을 반환하다가, `filled` 행이 1건이라도 추가되면 FIFO 경로로 전환되며 **0.0으로 급락**하는 것을 실측 확인.
- 1차 지적("status='loss' 죽은 쿼리")은 이미 FIFO 기반으로 일부 고쳐진 상태였으나, legacy/FIFO 두 경로가 공존하면서 여전히 손실 한도가 무력화되는 새로운 형태로 재발.
- `tests/test_trading_core.py`의 관련 테스트는 legacy 분기만 검증 — FIFO 경로의 날짜 필터링은 무테스트.
- **개선안**: legacy 폴백 제거(1회 마이그레이션), FIFO 경로 단일화 + 날짜 필터링 회귀 테스트 추가.

## 🟠 High — 신규 발견

| # | 문제 | 위치 | 담당 |
|---|---|---|---|
| 15 | live 모드에 포트폴리오(현금/보유수량) 검증이 아예 없음 — `application.py`가 paper일 때만 `PortfolioState` 주입, live는 `portfolio=None`이라 한도 검사 자체가 스킵됨 | `application.py:63-66`, `order_manager.py:51` | 리스크/QA |
| 16 | 중복 주문 방지가 원자적이지 않음 — `has_order_id` 조회 후 INSERT 사이 경쟁, `client_order_id`에 UNIQUE 인덱스 없음 | `order_manager.py:44`, `sqlite.py:24-39` | 아키텍처 |
| 17 | `daily_realized_loss`가 매 주문마다 DB 전체 이력을 풀스캔(기간 필터 없음) — 이력이 쌓일수록 주문 경로 지연이 선형 증가 | `sqlite.py:66-114` | 성능 |
| 18 | 인덱스 전무 — `has_order_id`/`pending_order_ids`/`update_order_status` 전부 인덱스 없는 컬럼 조회로 매 주문/사이클 풀스캔 | `sqlite.py:23-45` | 성능 |
| 19 | 틱 1건마다 SQLite 신규 커넥션 + 커밋(fsync) — WAL 미설정, 초당 수백 틱 유입 시 추론 루프가 디스크 I/O에 묶여 큐가 밀림 | `worker.py:48`, `sqlite.py:16-19,160` | 성능/퀀트 |
| 20 | 거래소 체결시각 대신 수신시각(`datetime.now`) 사용 — 학습(체결시각 축)과 라이브(수신시각 축) 피처 시간축이 네트워크 지연만큼 어긋남(재현 불가능한 피처) | `kis_websocket.py:106` | 퀀트 |
| 21 | Redis 클라이언트에 타임아웃/헬스체크 없음 — 응답 없는 Redis에 런타임 스레드가 무한 블록 가능 | `redis_queue.py:28,62` | 아키텍처 |
| 22 | WebSocket 정상 종료(`async for` 소진) 시 재접속 없이 조용히 피드 사망, 알람 없음 + 여러 예외 타입이 catch 밖 | `kis_websocket.py:116-131` | QA/아키텍처 |
| 23 | Rate Limit/재시도 전무 — 1초 주기 폴링이 최대 100페이지 페이지네이션과 겹치면 KIS 초당 한도 초과 확실 | `kis_rest.py`, `runtime.py` | QA |

## 🟡 Medium — 신규 발견

- 재시작 후 첫 MA 크로스가 구조적으로 누락됨 — 커서는 영속화되지만 가격 deque는 아니라서 재시작마다 워밍업 20틱 무신호 (`moving_average.py:32-33`)
- 틱 카운트 기반 MA와 시간 기반 피처 불일치 — 종목별 틱 도착률 차이로 동일 파라미터가 종목마다 다른 시간 윈도우를 의미, `tick.timestamp` 미검증이라 역순/중복 틱도 그대로 반영 (`moving_average.py:25-29`)
- `OrderManager.submit`에 락 없음(TOCTOU) — risk/portfolio 검사와 `apply` 사이가 원자적이지 않아 다중 워커에서 한도 우회 가능 (`order_manager.py:43-85`)
- 텐서 서빙 구조 부재 확인 — `models/` 빈 디렉터리, `SignalPredictor` Protocol이 단건 인터페이스라 배치 추론 자체가 불가능(현재는 YAGNI로 타당, DL 도입 시 Protocol 변경 선행 필요)
- 미사용 import `worker.py:7`의 `SignalAction`

## ✅ 1차 지적 중 이미 반영된 것으로 재확인된 항목

- Redis `xadd`에 `maxlen=..., approximate=True` 트리밍 적용됨 (`redis_queue.py:37`) — 1차 지적 #13 해결.
- WebSocket 틱 발행이 `asyncio.to_thread`로 감싸져 이벤트 루프 블로킹 해소됨 (`kis_websocket.py:136`) — 1차 지적 #12 해결.
- `client_order_id`가 틱 시각 기반으로 전파되어 시그널 시각이 추론시각에 오염되지 않음 — 1차 지적 #7 일부 해결.
- `last_id` 커서가 SQLite에 영속화되어 재기동 시 전체 리플레이는 더 이상 발생하지 않음 — 1차 지적 #3(스트림 전체 리플레이) 해결. 다만 그 대가로 위 12번(라우팅 실패 시 소실)이 새로 생김.

## 우선순위 액션 (2차 통합)

1. **커서 저장을 `on_signal` 성공 이후로 이동** — 라우팅 실패 시 신호가 영구 소실되는 현재 구조가 가장 시급. 회귀 테스트 1건으로 검증 가능.
2. **`client_order_id` 항상 채우기 + `attach_broker_order` 실패를 명시적으로 처리** — 유령 주문(로컬은 pending, 브로커는 체결)을 막아야 리컨실리에이션이 의미를 가짐.
3. **`is_open` 판정에 현재 시각 주입 + 격차 임계값 거부** — 백로그 재생 시 장 마감 후 오발주 차단.
4. **`daily_realized_loss` legacy 폴백 제거, FIFO 단일 경로화 + 날짜 필터링** — 손실 한도가 반복해서 무력화되는 근본 원인 제거.
5. **live 모드 포트폴리오 필수 주입 + SQLite WAL/인덱스 추가** — 안전장치 공백과 성능 병목을 함께 해소.

---
*2차 검토 담당: system-architect, quant-feature-engineer, risk-gate, perf-infra-profiler, qa-backtest-reviewer (병렬 read-only 재검토, 코드 수정 없음)*

---

# 3차 재검토 (2026-08-16, 라운드 3)

동일한 5개 서브에이전트로 또다시 처음부터 재검토. 2차 지적 사항의 실제 반영 여부를 재확인하고 신규 결함을 탐색. **2차 지적 다수(라우팅 후 커서 커밋, is_open 벽시계 판정, `attach_broker_order` client_order_id 채움, Redis 타임아웃/헬스체크, SQLite 인덱스, WebSocket reconnects 리셋, Rate Limit)가 이미 코드에 반영되어 있음을 확인**했다. 다만 그 수정들이 새로운 부작용을 낳은 경우도 발견됐다(아래 24, 29번 등).

## 🔴 Critical — 신규 발견

### 24. KIS 모의투자(VTTC) 모드가 실제로 배선되어 있지 않음 — "모의투자 스트레스 테스트" 자체가 구조적으로 불가능
(QA 신규 지적)

- `src/application.py:52,96`이 `paper_trading` 플래그로 실거래 TR(TTTC)과 **DB 내부 시뮬레이션**만 나누고, KIS 실제 모의투자 서버(VTTC/모의계좌 31000번대)로 라우팅하는 경로가 없음.
- `PAPER_TRADING=true`여도 페이퍼 모드에서는 `build_reconciler`가 `None`이 되어 **부분체결/거부 FSM이 단 한 번도 실행되지 않음** — 리스크 게이트 팀이 지적한 분할체결/거부 관련 결함들이 페이퍼 경로에서는 아예 검증 불가능한 구조.
- **개선안**: `KIS_ENV=paper|live` 같은 별도 축 도입해 VTTC 경로를 열고, 그 위에서 실제 모의투자 스트레스 테스트를 수행.

### 25. 테스트 실행이 실계좌에 진짜 주문을 낼 수 있음
(QA 신규 지적)

- `conftest.py` 부재 + `Settings` 기본값이 import 시점 `.env`를 그대로 읽음.
- 실 credential이 설정된 머신에서 `PAPER_TRADING=false` 상태로 `tests/test_application_pipeline.py`를 돌리면 KIS에 **실제 주문 POST**가 나갈 수 있음.
- **개선안**: 세션 단위 pytest 픽스처로 KIS 관련 env를 전부 비우고 `PAPER_TRADING=true`를 강제.

### 26. 브로커 거부 후 재시도가 "성공(duplicate)"으로 오보고
(QA가 실측 재현, 아키텍처/리스크 동일 계열 지적)

- `src/engine/order_manager.py:77-89` — write-ahead `pending` 행 저장 후 `executor.submit()`이 실패하면 그 pending 행이 그대로 남음.
- 동일 신호로 재시도하면 `has_order_id`에 걸려 **`accepted=True, "duplicate order already recorded"`로 반환** — 실제로는 한 번도 주문이 나가지 않았는데 상위 호출자는 성공으로 오인.
- QA 실측: `1st: accepted=False` → `2nd: accepted=True, 'duplicate order already recorded'`.
- **개선안**: `executor.submit` 실패 시 pending 행을 `rejected`로 마킹(또는 삭제)해서 재시도가 실제 재제출이 되게 함.

### 27. 부분체결 후 잔량취소 시 체결분이 통째로 소실
(QA 실측 재현, 리스크 게이트 재확인)

- `src/api/kis_rest.py:280-283` — `cncl_yn=Y`(취소여부) 판정이 `tot_ccld_qty>0`(부분체결)보다 우선순위가 높아, 10주 중 5주 체결 후 잔량 취소 시 상태가 그냥 `cancelled`로만 기록됨.
- QA 실측: 이 경우 `executed_trade_totals()` 결과가 `[]` — **보유 5주가 로컬 기록에서 완전히 사라짐**, 손실 한도 집계에서도 제외.
- **개선안**: `OrderStatusUpdate`에 `filled_quantity`/`avg_price` 추가해 체결 수량 기반으로 포지션/손익 반영.

### 28. KIS 웹소켓 멀티레코드 프레임에서 다수 체결이 버려짐
(퀀트&피처 신규 지적)

- `src/api/kis_websocket.py:95-107` — H0STCNT0 프레임은 `parts[2]`에 레코드 건수 n을, `parts[3]`에 n개의 체결 데이터를 연속 배치해서 보내는데, 코드는 건수를 무시하고 앞 13개 필드만 읽어 **1건만 파싱**.
- 고빈도 거래 종목에서 체결 데이터 대량 유실 → 이동평균이 실제 시세와 다른 계열 위에서 계산됨(피처가 사실과 다른 데이터로 만들어짐).
- **개선안**: `parse_message`를 레코드 건수 기반 루프로 재작성.

## 🟠 High — 신규 발견

| # | 문제 | 위치 | 담당 |
|---|---|---|---|
| 29 | Poison 메시지 파이프라인 영구 정지 — 2차에서 커서를 라우팅 이후로 옮긴 부작용. `on_signal` 예외 시 커서 미전진, `runtime.py`가 예외를 삼키고 다음 사이클에 같은 메시지 무한 재시도 | `worker.py:44-52`, `runtime.py:47-49` | 아키텍처/퀀트/QA 3중 지적 |
| 30 | WebSocket 정상 종료 시 재연결 불가 — 서버가 정상 종료(`async for` 소진)하면 `KISWebSocketError`를 던지는데 except 튜플에 없어 재연결 없이 피드가 조용히 사망 | `kis_websocket.py:127-128` | 아키텍처/QA |
| 31 | 라이브 주문에서 브로커 접수~ODNO 부착 사이 크래시 시 고아 주문 방치, 경보 없음 | `order_manager.py:77-89`, `sqlite.py:130-137` | 아키텍처 |
| 32 | `client_order_id`가 non-unique 인덱스 — 동시 두 워커가 동일 신호를 중복 주문 가능(TOCTOU의 근본 원인) | `sqlite.py:41-43` | 리스크 |
| 33 | Rate Limiter가 KISRestClient 인스턴스 단위 — order manager용/reconciler용을 각각 생성해 실효 한도가 40req/s로 2배 새고 토큰도 중복 발급됨 | `application.py:41,86` | 리스크 |
| 34 | 총 노출 한도 부재 — 건당 금액과 실현손실만 검사, 미체결 명목가/일일 주문건수/심볼 집중도/미실현손실 한도 없음 | `risk.py:29-32` | 리스크 |
| 35 | reconcile()이 추론 루프와 같은 스레드에서 매 사이클(기본 1초) REST 호출 — rate limit 대기(`time.sleep`)가 틱 처리를 그대로 정지시킴, 미체결 적체 시 틱 처리 완전 기아 | `runtime.py:52-54`, `kis_rest.py:52-62,237` | 성능 |
| 36 | 틱 1건마다 `save_stream_cursor` 신규 커넥션+fsync — 배치 끝 1회 커밋이면 충분한데 틱마다 디스크 동기화 | `worker.py:52` | 성능 |
| 37 | `daily_realized_loss`가 여전히 하한 없는 전량 스캔(상한만 있음) — 이력 누적에 비례해 매 주문 지연 증가 | `sqlite.py:82-86` | 성능/아키텍처 |
| 38 | 거부된 주문(`OrderResult.accepted=False`)이 메트릭/알림 어디에도 안 잡힘 — 리스크·장시간·현금부족으로 자동매매가 전량 거부되는 상태를 탐지할 수단이 없음 | `monitoring/metrics.py` | QA |

## 🟡 Medium — 신규 발견

- 콜드스타트 리플레이: 커서가 없을 때 `"0-0"`부터 최대 10만 건 과거 틱을 재생, 페이퍼 모드 `is_open` 판정이 여전히 `order.timestamp` 기준이라 과거 가격 주문이 통과 (`worker.py`, `order_manager.py:48-50`)
- 처리량 미스매치로 조용한 틱 드롭 — poll 1초 × count=10인데 유입이 이를 초과하면 `maxlen` 트리밍이 미처리 틱을 삭제, MA 윈도우에 재현 불가능한 구멍 발생 (`runtime.py:86`, `redis_queue.py:38`)
- 타임스탬프 누락 시 조용히 `datetime.now()`로 대체 + naive 타임스탬프를 무조건 UTC로 간주 → KST naive 값 유입 시 9시간 시프트 (`worker.py:20-23`, `models.py:18`)
- `moving_average.py`가 틱마다 `list(prices)` 전체 복사 + `sum()` 재계산 — 증분 합으로 O(1) 가능 (측정 없이 손대지 말 것)
- mocking이 계약 위반을 은폐 — `FakeReconciler.reconcile()`이 임의 문자열을 반환해도 `metrics.py`의 `getattr(..., "updated", 0)` 폴백 때문에 테스트가 초록으로 통과 (`tests/test_runtime.py`)
- Rate limiter(`_wait_for_rate_limit`) 자체에 대한 테스트 0건 — 경계/경합 회귀를 못 잡음
- reconnects 카운터 리셋이 구독 이전 시점이라 연결 플래핑 시 무한 재연결 가능성 (2차 "리셋 없음" 지적의 수정판이 낳은 새 문제)
- paper 포트폴리오가 기동 시 1회만 DB에서 복원됨 — 런타임 중 reconciler의 filled 반영이 반영되지 않음

## ✅ 2차 지적 중 이미 반영된 것으로 재확인된 항목

- 커서가 `on_signal`(라우팅) 성공 이후로 커밋되도록 수정됨 — 단, 이 수정이 위 29번(poison 메시지 무한정지)의 원인이 됨. 트레이드오프 재확인 필요.
- `is_open` 판정이 라이브 모드에서는 벽시계 기준으로 전환됨 — 페이퍼 모드는 여전히 `order.timestamp` 기준으로 잔존.
- `attach_broker_order` 저장 시 `client_order_id`가 항상 채워짐, 조건부 UPDATE의 rowcount 검증도 확인됨.
- `daily_realized_loss`의 legacy 폴백이 `if rows:` 가드로 사실상 무력화되어 은폐 위험은 해소. 단, 하한 없는 전량 스캔 성능 문제(37번)는 잔존.
- Rate Limit이 `kis_rest.py:52-62`에 구현됨 — 단, 인스턴스 단위라 실효 한도가 새는 33번 문제가 새로 발견됨.
- SQLite 인덱스 3개 추가됨, WAL+busy_timeout 적용 확인.
- WebSocket `reconnects` 카운터 리셋 로직 추가됨 — 단, 리셋 타이밍 이슈(구독 이전) 잔존.
- Redis 클라이언트에 `socket_timeout`/헬스체크 적용 확인.

## 우선순위 액션 (3차 통합)

1. **KIS 실제 모의투자(VTTC) 경로 배선 + 테스트 환경 격리(`conftest.py`)** — 지금은 "모의투자 스트레스 테스트"가 성립 자체가 안 되고, 테스트가 실주문을 낼 위험까지 있음. 다른 모든 안전장치보다 먼저 막아야 할 손실 통제.
2. **poison 메시지 처리와 커서 커밋 순서의 트레이드오프 해소** — 라우팅 실패 시 신호 소실(2차) vs 파이프라인 영구 정지(3차) 사이에서, 실패 유형별로 분기(파싱 실패는 스킵+전진, 라우팅 실패는 재시도 한도를 두고 전진)하는 설계가 필요.
3. **웹소켓 멀티레코드 파싱 수정** — 피처가 잘못된 시세 위에서 계산되고 있다는 것은 리스크·성능 이전에 데이터 정합성 문제. 최우선 버그 수준.
4. **주문 실패/성공 상태 전이 정리** — pending 행이 실패 후에도 남아 재시도를 "성공"으로 오인시키는 구조, 부분체결 취소 시 체결분 소실. `filled_quantity` 컬럼 도입으로 근본 해결.
5. **reconcile 주기를 추론 루프와 분리 + KISRestClient 인스턴스 단일화** — 안전장치와 성능 문제가 같은 원인(단일 스레드, 다중 클라이언트)에서 나오므로 함께 해결.

---
*3차 검토 담당: system-architect, quant-feature-engineer, risk-gate, perf-infra-profiler, qa-backtest-reviewer (병렬 read-only 재검토, 코드 수정 없음)*

---

# 4차 재검토 (2026-08-16, 라운드 4)

동일한 5개 서브에이전트로 재검토. 이번 라운드의 핵심 패턴은 **"고친 게 새 결함을 낳는" 연쇄**다: 3차에서 poison 메시지 대응으로 넣은 수정, 멀티레코드 파싱 수정, `client_order_id` UNIQUE 인덱스가 각각 새로운 정지/오염 시나리오를 만들었다. 또한 QA가 **테스트 스위트 자체가 이 환경에서 37개 에러로 실패 중**임을 실측했고, 성능 에이전트가 처음으로 실측 프로파일링 수치를 냈다.

## 🔴 Critical — 신규 발견

### 39. 3차의 멀티레코드 파싱 수정이 필드 stride를 잘못 잡아 가짜 틱 생성
(퀀트&피처 신규 지적)

- `src/api/kis_websocket.py:103-107` — 3차에서 레코드 건수 기반 루프로 고쳤으나, 실제 H0STCNT0 레코드는 46필드인데 **13필드 stride**로 슬라이싱.
- count≥2인 프레임에서 2번째 레코드부터 종목코드 자리에 `ACML_VOL`(누적거래량) 같은 다른 필드값이 들어가 **엉뚱한 심볼/가격의 가짜 틱**이 생성됨.
- `tests/test_kis_websocket.py:97,122`의 테스트 픽스처 자체가 13필드짜리 가짜 프레임이라 이 버그가 그린으로 통과 중 — **버그가 테스트에 의해 고착화됨**.
- **개선안**: stride를 실제 필드 수(46)로 수정하고 테스트 픽스처를 실제 KIS 프레임 포맷으로 교체.

### 40. `client_order_id` UNIQUE 인덱스(3차 수정)가 거절 주문 재생 시 IntegrityError로 새로운 영구 정지 유발
(아키텍처 / 리스크 게이트 / QA 3중 지적)

- 3차에서 중복 주문 방지를 위해 `client_order_id`에 UNIQUE 인덱스를 추가했는데, `has_order_id`(`sqlite.py:51,140`)가 `rejected` 상태를 조회 대상에서 제외.
- 거절된 주문과 동일한 신호(같은 `client_order_id`)가 재생되면 `save()`가 UNIQUE 제약 위반으로 `sqlite3.IntegrityError`를 던짐 — 이는 `ValueError`가 아니므로 워커의 poison 처리 로직도 이를 못 잡고 **커서가 전진하지 못해 매 사이클 동일 틱에서 영구 스톨**.
- QA 실측: 76 passed / **37 errors**로 로컬 테스트 스위트가 이미 이 계열 문제로 깨져 있음(단, 직접 원인은 아래 41번).
- **개선안**: `has_order_id`의 상태 필터를 제거(모든 이력 조회)하거나, `save()`를 `INSERT ... ON CONFLICT(client_order_id) DO NOTHING`으로 변경.

### 41. `TradeRepository._connect()`가 커밋만 하고 close를 안 함 — 테스트 스위트가 실제로 깨져 있음
(QA 실측)

- `src/database/sqlite.py:16` `with` 블록이 커밋만 하고 커넥션을 닫지 않아 WAL/shm 핸들이 잔류.
- 실측: 이 환경에서 pytest 실행 시 **76 passed / 37 errors** — tmp_path 정리 시 `PermissionError`로 대량 에러 발생.
- 회귀 감지 기능이 1/3 가량 무력화된 상태이며, 장기 구동 시 파일 디스크립터 누수로 이어짐.
- **개선안**: 커넥션 close를 보장하는 컨텍스트 매니저로 교체.

### 42. 부분체결 + 거부 조합 시 체결분 완전 소실
(리스크 게이트 신규 지적)

- `src/api/kis_rest.py:281` — `rjct_qty>0`(거부 수량)을 최우선으로 판정해 `status="rejected"`로 기록.
- KIS는 부분거부(일부는 체결, 잔량은 거부)도 `rjct_qty>0`으로 응답할 수 있는데, P&L 집계(`sqlite.py:95`)와 포트폴리오 복원(`sqlite.py:200`) 쿼리의 status 필터에 `rejected`가 빠져 있어 **이 행 전체가 무시됨**.
- 실제로는 일부 체결된 유령 포지션이 남고, 일일 손실이 과소집계되어 손실 한도가 우회됨.
- **개선안**: 판정 순서를 "체결분 우선"으로 바꾸고, P&L/포트폴리오 쿼리가 `filled_quantity>0`인 `rejected` 행도 포함하도록 수정.

## 🟠 High — 신규 발견

| # | 문제 | 위치 | 담당 |
|---|---|---|---|
| 43 | 브로커 응답 타임아웃 시 로컬을 `rejected`로 기록하지만 실주문은 브로커에 남아있고 `broker_order_id`가 없어 reconcile 대상에서 영원히 제외 — 좀비 주문 | `order_manager.py:84-91` | 리스크 |
| 44 | `attach_broker_order` 실패 시 `RuntimeError`로 실주문만 남고 로컬은 매칭 불가능한 pending으로 좀비화 | `order_manager.py:89-90` | 리스크 |
| 45 | 미체결 타임아웃/취소 API가 코드 전체에 부재 확인(3차부터 반복 지적, 여전히 미해결) | 전역 | 리스크 |
| 46 | `build_pipeline`이 `InferenceWorker(on_error=...)`를 배선하지 않음 — 수량 미설정/포트폴리오 부족 등 ValueError가 로그·메트릭 없이 삼켜지고 커서만 전진, 주문이 무음 소실 (QA 실측) | `application.py:122` | QA |
| 47 | 부분체결 후 취소 시 `filled_quantity`가 `SET`(대입)이라 MAX가 아니어서 실측상 0으로 되돌아감 — 3차 지적의 근본 원인 특정 | `order_manager.py`/`sqlite.py` UPDATE 쿼리 | QA |
| 48 | 페이퍼 주문 ID가 `paper-{timestamp}`로 종목 구분 없이 생성 — 동일 타임스탬프에 다른 종목 신호가 겹치면 `broker_order_id` 충돌 (틱 리플레이 시 실제 발생) | `order_manager.py` 페이퍼 경로 | QA |
| 49 | 라이브 모드에서 `KISRestClient`가 주문용/정합성용 2개 인스턴스로 생성 — 토큰 캐시가 인스턴스별이라 `/oauth2/tokenP` 2배 호출, KIS 분당 1회 토큰 발급 제한에 걸릴 수 있음. `TradeRepository`도 3곳에서 생성돼 DDL이 반복 실행됨 | `application.py:41,86,37,77,99` | 성능/아키텍처 중복 지적 |
| 50 | rate limiter가 클래스 변수로 공유되지만 우선순위가 없어, 정합성 조회(최대 100페이지)가 20rps 슬롯을 독점하면 손절 주문 제출이 수 초 지연될 수 있음 | `kis_rest.py:52-62,237` | 성능 |
| 51 | WebSocket 수집기(`stream_to_queue`)가 프로덕션 엔트리포인트 어디에도 배선되지 않음 — 현재 실제로 Redis에 틱을 넣는 프로덕션 경로가 없음(테스트에서만 사용) | `src/cli.py`, 전역 | 성능/아키텍처 중복 지적 |
| 52 | WebSocket 정상 종료 시 재연결 안 되는 문제가 4차에도 재확인됨(2차→3차→4차 연속 미해결) | `kis_websocket.py:135-136` | 아키텍처/QA |

## 🟡 Medium — 신규 발견 (실측 포함)

- **실측 프로파일링(성능 에이전트, 로컬 2000행 기준)**: `save` 12.3ms/op, `save_stream_cursor` **10.3ms/틱**, `daily_realized_loss` 15.9ms/호출. 커넥션 생성 자체는 0.83ms로 미미 — 병목은 **커밋 시 fsync**. 현재 구조의 처리량 상한이 대략 **초당 97틱**으로 실측 확인됨.
- `PRAGMA journal_mode = WAL`이 매 커넥션 생성마다 재실행됨 — WAL은 DB 파일에 영구 저장되므로 순수 낭비이고, 트랜잭션 컨텍스트 안에서 실패해도 조용히 무시됨 (`sqlite.py:20`)
- Redis 스트림이 `maxlen` 트림된 구간을 커서가 가리키면 `xread`가 조용히 건너뜀 — 틱 유실을 감지할 갭 메트릭이 없음 (`redis_queue.py:38`)
- `publish` 예외 시 `stream_to_queue` 태스크 자체가 죽고 재시도·백프레셔가 없음 — 생산자 측 유일한 유실 방지 장치 부재 (`kis_websocket.py:142-150`)
- `RedisQueue.read()`가 항목 하나만 깨져도 배치 전체를 `RedisQueueError`로 실패시켜 poison 처리가 여전히 부분적으로만 동작 (`redis_queue.py:66-69`)
- 신규 DB에 기존 중복 `client_order_id`가 있으면 UNIQUE 인덱스 생성 자체가 실패해 `TradeRepository()` 생성이 예외를 던지고, 엔진/헬스/정합성이 전부 기동 불가 — 마이그레이션 경로 없음
- NaN 가격이 검증을 통과함(`price<=0` 검사만 있어 `float("nan")` 통과) — deque에 들어가면 해당 심볼 MA가 20틱 동안 NaN이 되어 신호가 예외 없이 영구 침묵 (퀀트 신규 지적, `models.py:46`)
- 거래소 체결시각(`group[1]`)이 여전히 폐기되고 wall-clock 사용 — 재접속 버스트/큐 지연 시 다수 틱이 동일 시각으로 뭉개져 train/serve skew 발생 (3차부터 반복 지적, 여전히 미해결)
- `test_runtime.py`의 mock이 여전히 계약 위반을 은폐 — `reconcile()`이 임의 문자열을 반환해도 통과 (3차부터 반복 지적)

## ✅ 3차 지적 중 이번에 반영 확인된 항목

- poison 메시지 무한정지(3차 #29)는 `worker.py:51`에서 `ValueError`에 한해 해결됨 — 단, `IntegrityError`(40번)와 `RedisQueueError`(배치 전체 실패)는 여전히 잡지 못함.
- 브로커 거부 후 "성공(duplicate)" 오보고(3차 #26)는 `sqlite.py:140`이 `rejected`를 제외하도록 수정되어 해결됨 — 단, 그 수정이 새로운 IntegrityError 정지(40번)를 낳음.
- `client_order_id` non-unique 인덱스(3차 #32)는 UNIQUE 인덱스로 해결됨 — 단, 부작용(40번) 발생.
- KISRestClient rate limiter가 클래스 변수로 공유되어 실효 40rps로 새던 문제(3차 #33)는 해결됨 — 단, 인스턴스 자체는 여전히 2개라 토큰 발급이 중복되는 별도 문제(49번)로 재발.
- 웹소켓 멀티레코드 파싱(3차 #28)은 카운트 기반 루프로 고쳐졌으나 stride 오류(39번)로 대체됨.

## 우선순위 액션 (4차 통합)

1. **`TradeRepository._connect()` 커넥션 close 보장 + `conftest.py` 도입** — 테스트 스위트가 이미 37개 에러로 깨져 있어 이후 모든 검증이 신뢰할 수 없는 상태. 다른 무엇보다 먼저 고쳐야 나머지 수정의 효과를 검증할 수 있음.
2. **`has_order_id` 필터 제거 또는 UPSERT로 전환** — 3차 수정이 낳은 새로운 poison(IntegrityError) 제거.
3. **웹소켓 파싱 stride를 실제 필드 수로 수정 + 테스트 픽스처를 실제 KIS 프레임으로 교체** — 지금은 버그가 테스트에 의해 고착되어 있어 다음 재검토에서도 "정상"으로 보고될 위험.
4. **`filled_quantity`를 단조 갱신(MAX)으로, 부분거부 조합도 P&L/포트폴리오에 포함** — 체결분 소실 계열 결함의 근본 원인.
5. **`save_stream_cursor` 배치 커밋 전환 + `KISRestClient`/`TradeRepository` 인스턴스 단일화** — 실측된 처리량 상한(초당 97틱)을 올리는 가장 확실한 지렛대.

---
*4차 검토 담당: system-architect, quant-feature-engineer, risk-gate, perf-infra-profiler, qa-backtest-reviewer (병렬 read-only 재검토, 코드 수정 없음)*

---

# 실제 수정 작업 (2026-08-16)

4차례 재검토로 쌓인 지적사항을 다시 복기하며 실제 코드 수정을 진행했다. 항목이 많아 전부를 한 번에 고치기보다, **가장 근본적이고 검증 가능한 것부터** 고치는 방식으로 우선순위를 매겼다. 모든 수정은 회귀 테스트로 뒷받침했고, 수정 전/후 전체 테스트 스위트를 실행해 확인했다(최종 119 passed).

## 수정 완료

### 1. 테스트 스위트 자체가 깨져 있던 원인 제거 (4차 #41)
`src/database/sqlite.py` — `TradeRepository._connect()`가 반환한 커넥션을 `with connection:`으로만 사용해왔는데, 이는 커밋/롤백만 하고 **소켓을 닫지 않는다**. WAL/shm 핸들이 매 호출마다 누적되어 Windows에서 tmp 디렉터리 정리가 `PermissionError`로 실패하고 있었다(로컬에서 76 passed/37 errors로 실측 확인됨).
`_transaction()` 컨텍스트 매니저를 추가해 모든 메서드가 `finally: connection.close()`를 거치도록 정리했다. 이 수정 하나로 37개 에러가 전부 사라졌다.
*(참고: 이 세션에서 pytest의 기본 임시 디렉터리(`%TEMP%\pytest-of-SDS`)는 수정 이전 세션들이 남긴 좀비 상태로 여전히 접근 자체가 막혀 있다. 코드 문제는 아니며, 사용자가 수동으로 지우거나 `--basetemp`를 지정하면 된다.)*

### 2. 거절된 주문 재시도 시 `IntegrityError`로 파이프라인이 영구 정지하던 문제 (3차 #40, 4차 재확인)
`src/database/sqlite.py` `save()` — `has_order_id()`는 의도적으로 `rejected` 상태를 제외해 재시도를 허용하지만, 재시도가 같은 `client_order_id`로 `INSERT`를 시도하면 UNIQUE 인덱스에 걸려 `sqlite3.IntegrityError`가 그대로 호출자에게 전파되어 워커의 poison 처리로도 못 잡고 매 사이클 동일 틱에서 영구 정지했다.
`INSERT ... ON CONFLICT(client_order_id) WHERE client_order_id IS NOT NULL DO UPDATE ... WHERE trade_logs.status = 'rejected'`로 바꿔, 거절된 행을 새로 삽입하는 대신 되살리도록 했다. 진짜 중복(pending/submitted/filled/simulated)은 `has_order_id()`가 여전히 앞단에서 차단하므로 안전장치는 그대로 유지된다.
회귀 테스트: `tests/test_order_safety.py::test_rejected_order_can_be_retried_with_the_same_client_order_id`

### 3. 웹소켓 멀티레코드 파싱 stride 오류로 가짜 틱이 생성되던 문제 (3차 #28 수정 → 4차 #39 발견)
`src/api/kis_websocket.py` `parse_ticks()` — 레코드 카운트 기반 루프로는 고쳐졌지만 필드 stride를 13으로 잘못 잡아, 2번째 레코드부터 다른 필드값이 심볼/가격 자리에 섞여 들어가는 가짜 틱이 만들어지고 있었다. 게다가 테스트 픽스처 자체가 13필드짜리라 이 버그가 그린으로 통과해왔다.
실제 KIS H0STCNT0 레코드 필드 수인 46(`_RECORD_FIELD_COUNT`)으로 stride를 수정하고, `tests/test_kis_websocket.py`의 픽스처를 46필드 헬퍼(`make_record`/`make_frame`)로 전면 교체했다.
회귀 테스트: `test_multi_record_frame_yields_one_tick_per_record`

### 4. 거래소 체결시각 대신 수신시각을 쓰던 문제 (2~4차 반복 지적)
같은 파일 — `datetime.now(timezone.utc))` 대신 KIS가 보내는 체결시각 필드(`group[1]`, KST HHMMSS)를 파싱해 UTC로 변환하도록 `_execution_timestamp()`를 추가했다. 재접속 버스트나 큐 지연 시 다수 틱이 동일 수신시각으로 뭉개지던 것을 방지하고, 학습(체결시각 기준)과 라이브(이제 체결시각 기준)의 피처 시간축을 일치시켰다.
회귀 테스트: `test_execution_time_field_is_used_for_tick_timestamp`

### 5. NaN/무한대 가격이 검증을 통과하던 문제 (4차 신규)
`src/models.py` `Tick.__post_init__` — `price <= 0`만으로는 `float("nan") <= 0`이 `False`라 NaN이 통과했다. `math.isfinite()` 체크를 추가해 NaN/±inf를 모두 거부한다. 이전에는 NaN 한 틱이 들어오면 해당 심볼의 이동평균이 윈도우 길이만큼(기본 20틱) 조용히 NaN으로 침묵했다.
회귀 테스트: `tests/test_trading_core.py::test_tick_rejects_nan_and_infinite_price`

### 6. 부분체결 후 거절/취소 시 체결분이 P&L·포지션에서 사라지던 문제 (3차 #42, 4차 재확인)
- `src/api/kis_rest.py` `_parse_update()` — 상태 판정 순서를 "완전체결 → 취소 → 거절 → 진행중"으로 재정렬해, 부분체결 후 거절된 주문도 `filled_quantity`를 유지한 채 상태가 결정되도록 했다.
- `src/database/sqlite.py` `daily_realized_loss()`/`executed_trade_totals()` — 쿼리의 상태 필터에서 `rejected`가 아예 빠져 있어 `filled_quantity > 0`인 거절 행이 통째로 무시되던 것을 필터에 포함시켰다.
회귀 테스트: `tests/test_trading_core.py::test_partial_fill_then_reject_keeps_filled_quantity_in_pnl`

### 7. Kill-Switch 부재 (1~4차에 걸쳐 반복 지적된 최우선 미해결 항목)
`src/engine/order_manager.py` — `OrderManager`는 모든 주문(라이브/페이퍼, 라우터/재시도 무관)이 지나가는 유일한 진입점이므로, 여기에 연속 브로커 거절 횟수 기반 kill-switch를 넣었다. `max_consecutive_rejections`(기본 3)를 넘기면 `halted=True`가 되어 이후 모든 `submit()` 호출이 사유와 함께 즉시 거부되고, 성공적인 제출이 있으면 카운터가 리셋된다. 해제는 `reset_halt()`로 수동으로만 가능하다.
연속 손실 금액이나 API 오류율 기반 트리거는 아직 없다 — "연속 거절"이라는 가장 명확하고 오탐이 적은 신호부터 최소 구현으로 시작했다.
회귀 테스트: `test_kill_switch_halts_after_consecutive_rejections`

### 8. 페이퍼 모드 주문 ID 충돌 (4차 #48)
같은 파일 — `paper-{timestamp}` 폴백이 종목 구분 없이 타임스탬프만 썼다. 틱 리플레이에서 동일 타임스탬프의 다른 종목 신호가 겹치면 `broker_order_id`가 충돌했다. `paper-{strategy}:{symbol}:{side}:{timestamp}`로 변경.

### 9. 틱 1건마다 SQLite fsync가 발생하던 문제 (3~4차, 실측 10.3ms/틱)
`src/inference/worker.py` `process_once()` — 메시지마다 `save_stream_cursor()`를 호출하던 것을 배치(최대 `count`건) 종료 시 1회만 호출하도록 `finally` 블록으로 옮겼다. 크래시 시 최대 1배치만큼 재처리될 수 있지만 주문 제출이 `client_order_id` 기반으로 멱등이라 안전하며, 실측된 처리량 상한(초당 약 97틱)을 끌어올리는 가장 직접적인 지렛대였다.

### 10. reconcile()이 추론 스레드를 기아시키던 문제에 대한 대응 메커니즘 추가 (3~4차)
`src/runtime.py` `TradingRuntime` — `reconcile_every` 파라미터를 추가해 정합성 확인(REST 페이지네이션, rate-limit 대기 포함)을 매 사이클이 아니라 N사이클마다 한 번만 돌릴 수 있게 했다. 기본값은 1(기존과 동일한 매 사이클 동작)로 두어 하위 호환을 유지했다 — `application.py`의 `build_runtime`에 아직 설정값으로 연결하지는 않았다(아래 "남겨둔 항목" 참고).

### 11. WebSocket 정상 종료 시 재연결되지 않던 문제 (2~4차 반복 지적)
`src/api/kis_websocket.py` `stream()` — KIS가 프로토콜 오류 없이 세션을 정상 종료하면(`async for`가 그냥 끝남) 예외 없이 스트림이 조용히 죽었다. 내부 전용 `_StreamClosedNormally` 신호를 추가해 이 경우도 기존 재연결 백오프 경로를 타도록 했다. 실제 프로토콜/파싱 오류(`KISWebSocketError`)는 여전히 즉시 전파되어, 데이터 정합성 문제를 재연결로 조용히 덮어쓰지 않는다.

### 12. 테스트가 실계좌에 도달할 수 있던 구조 (3차 #25)
`tests/conftest.py` 신규 추가 — 세션 시작 시 `PAPER_TRADING=true`와 빈 KIS 자격증명을 환경변수에 강제한다. `Settings`는 `load_dotenv()`를 쓰는데 이는 이미 설정된 값을 덮어쓰지 않으므로, conftest가 먼저 실행되는 한 실제 `.env`에 라이브 자격증명이 있어도 테스트에 반영되지 않는다. 라이브 배선을 의도적으로 검증하는 테스트는 `Settings(...)`에 명시적 kwargs를 넘기므로 영향받지 않는다.

## 검증

```
python -m pytest -q   # 119 passed (기존 113 + 신규 회귀 테스트 6개)
```

## 의도적으로 남겨둔 항목 (범위·리스크상 이번 세션에서 다루지 않음)

- **KIS 실제 모의투자(VTTC) 계좌 연동 배선** (3차 #24) — `KISOrderExecutor`/`KISRestClient`는 이미 `paper_trading` 플래그로 VTTC/TTTC 거래ID를 구분하는 코드를 갖고 있지만, `application.py`의 `build_order_manager`는 `is_paper=True`일 때 이 경로를 아예 타지 않고 로컬 DB 시뮬레이션으로 빠진다. 별도의 설정 축(실제 모의투자 계좌번호/자격증명)과 새 배선 경로, 그리고 그걸 검증할 테스트가 필요한 규모의 기능 추가라 이번 세션에서는 손대지 않았다.
- **총 노출 한도**(건당 금액 외 일일 주문건수/심볼 집중도/미실현손실) — `RiskGate`에 아직 없음.
- **미체결 타임아웃/자동 취소** — KIS 주문 취소 API(`TTTC0803U` 등) 자체가 코드에 없음.
- **`KISRestClient`/`TradeRepository` 인스턴스 공유** — order manager용과 reconciler용이 여전히 각각 생성됨(토큰 발급은 중복되지만 rate limiter는 클래스 변수 공유라 실효 한도 위반은 아님).
- **`daily_realized_loss`의 전체 이력 FIFO 스캔** — 정확성을 위해 매수 lot을 과거 전체에서 찾아야 하므로 날짜 하한을 단순히 자를 수 없다. 인덱스는 이미 있고(`idx_trade_status_timestamp`), 정말 병목이면 캐싱이나 별도 잔고 테이블이 필요한 구조적 문제라 보류.
- **`reconcile_every`를 `Settings`/`build_runtime`에 실제로 연결** — 메커니즘만 추가했고 기본값 1로 기존 동작을 유지. 운영 중 실측 후 값을 정하는 게 낫다고 판단.
- **거부된 주문(`accepted=False`)의 메트릭/알림 노출** — 자동매매가 조용히 전량 거부되는 상태를 감지할 수단이 여전히 없음.

---
*수정 담당: 메인 세션(read-only 검토가 아닌 실제 코드 수정). 위 항목 외의 review.md 상 지적사항은 아직 미착수 상태로 남아있다.*
