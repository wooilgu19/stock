# 틱 녹화/재생 (야간·주말 실전 관찰) 설계

## 배경

평일 장중(09:00~15:30 KST)에만 실전 시세로 매매 파이프라인을 관찰할 수 있었다.
사용자는 평일 장중 관찰이 어려워, 야간이나 주말에도 실제 시세 흐름으로 신호/주문
로직을 관찰하고 싶어 한다.

## 목표

- 평일 장중에 실시간 틱을 녹화해두고, 야간/주말에 그 틱을 원래 속도 그대로
  재생하여 매매 파이프라인(신호 생성 → 리스크 게이트 → 주문)이 실전과 동일하게
  동작하는지 관찰할 수 있게 한다.
- 신규 KIS API 연동(과거 시세 조회 등) 없이, 기존 웹소켓 수집 경로만 재사용한다.

## 비목표

- 배속 재생(고정 배속 옵션)은 이번 범위에 넣지 않는다. 필요해지면 나중에 추가.
- 과거 임의 날짜의 시세를 KIS 서버에서 가져오는 기능은 다루지 않는다(녹화된 것만 재생).

## 아키텍처

기존 구조: `src/main.py`의 웹소켓 수집기(`_run_collector`)가 KIS 실시간 틱을
Redis 큐(`stock:ticks`)에 publish하고, 매매 루프(`build_runtime`)가 그 큐를 읽어
신호를 만들고 주문을 낸다. 두 부분은 Redis 큐로만 연결되어 있어, 수집기 자리를
바꿔치기해도 매매 루프 쪽 코드는 그대로 재사용할 수 있다.

```
[평일]  KIS WS --stream_to_queue--> RecordingQueue --> Redis stream --> 매매 루프
                                         |
                                         v
                                   ticks_YYYYMMDD.jsonl

[야간/주말]  replay_ticks(file) --publish--> Redis stream --> 매매 루프 (동일 코드)
```

## 컴포넌트

### 1. `RecordingQueue` (신규, `src/queue/recording_queue.py`)

`RedisQueue`와 동일한 `publish(message)` 인터페이스를 갖는 얇은 래퍼.
`publish()` 호출 시:
1. 내부에 감싼 실제 큐(`RedisQueue`)로 그대로 전달한다 (평소처럼 매매도 동작).
2. 같은 메시지를 `{"ts": time.time(), "payload": message}` 형태로 JSONL 파일에
   한 줄 append한다.

파일 쓰기가 실패해도(디스크 이슈 등) 예외를 삼키고 로그만 남긴다 — 녹화 실패가
실거래를 막으면 안 된다.

### 2. 재생 코루틴 `replay_ticks` (신규, `src/replay.py`)

```python
async def replay_ticks(path: str, queue: TickQueue, stop_event: threading.Event) -> None:
```

- JSONL 파일을 한 줄씩 읽어 `{"ts": ..., "payload": ...}`로 파싱.
- 파일이 비어있거나 첫 줄 파싱에 실패하면 `ValueError`를 즉시 발생시켜 종료
  (조용히 아무 신호도 안 뜨는 상태를 방지).
- 각 줄 사이의 `ts` 차이만큼 `asyncio.sleep`한 뒤 `queue.publish(payload)` 호출.
  첫 줄은 대기 없이 즉시 publish.
- `stop_event`가 set되면 다음 sleep 전에 루프를 빠져나온다(Ctrl+C 대응).
- 마지막 줄까지 재생하면 정상 종료(현재 `_run_collector`가 스트림 종료 시
  `stop_event.set()`으로 매매 루프도 같이 멈추는 동작을 그대로 재사용).

### 3. `src/main.py` CLI 확장

- `--record <경로>`: 지정 시 `_run_collector`가 `RedisQueue` 대신
  `RecordingQueue(RedisQueue(...), path)`를 사용. 라이브 수집기(KIS 웹소켓)는
  그대로 동작.
- `--replay <경로>`: 지정 시 KIS 웹소켓 수집기를 아예 띄우지 않고, 대신
  `replay_ticks(path, queue, stop_event)`를 돈다. 이 모드에서는
  `KIS_APPKEY`/`KIS_APPSECRET` 검증을 건너뛴다(재생은 KIS 인증이 필요 없음).
- `--record`와 `--replay`를 동시에 지정하면 `SystemExit`으로 즉시 에러.

### 4. 장 시간(MarketHours) 가드 우회

`OrderManager.submit`은 `MarketHours.is_open()`을 **실제 벽시계**로 체크해서
장 마감 시간엔 주문을 거절한다(`src/engine/order_manager.py`). 재생 틱은
"과거 장중" 데이터이지만 재생 시각은 밤/주말이므로, 이 체크를 그대로 두면
재생 내내 모든 신호가 거절되어 버린다.

해결: `build_order_manager` / `build_pipeline` / `build_runtime`에
`enforce_market_hours: bool = True` 파라미터를 추가한다. `False`면
`OrderManager(market_hours=None, ...)`로 만들어 이 체크를 완전히 건너뛴다.
`main.py`는 `--replay`가 주어졌을 때만 `enforce_market_hours=False`로 넘긴다.
평소 라이브 실행은 기존과 동일하게 항상 `True`.

## 에러 처리

- 녹화 파일 쓰기 실패: 로그만 남기고 계속 (치명적 아님).
- 재생 파일 없음/빈 파일/파싱 실패: 즉시 에러로 프로세스 종료.
- `--record`와 `--replay` 동시 지정: 시작 시점에 즉시 에러.

## 테스트

- `RecordingQueue`: `publish()` 호출 시 내부 큐로도 전달되고, 파일에도 한 줄
  기록되는지 (내부 큐는 fake로 대체).
- `RecordingQueue`: 파일 쓰기가 예외를 던져도 내부 큐 publish는 성공하는지.
- `replay_ticks`: 2~3줄짜리 fake 파일로, `asyncio.sleep`이 각 줄 사이 `ts` 차이만큼
  호출되는지, 각 payload가 순서대로 queue에 publish되는지 (sleep은 monkeypatch로
  실제 대기 없이 검증).
- `replay_ticks`: 빈 파일/깨진 첫 줄에서 `ValueError` 발생 확인.
- `build_order_manager(..., enforce_market_hours=False)`가 `OrderManager.market_hours`를
  `None`으로 만드는지 (기존 `enforce_market_hours=True`/기본값은 회귀 없는지 함께 확인).

## 사용 예시

```powershell
# 평일 장중 (녹화 + 정상 매매)
python -m src.main 005930 --record ticks_20260907.jsonl

# 야간/주말 (재생만, 실제 매매는 paper 모드로 관찰)
python -m src.main 005930 --replay ticks_20260907.jsonl
```
