# 딥러닝(LSTM) 신호 전략 연결 설계

## 배경

지금까지의 신호 엔진은 `MovingAverageStrategy`(단순 이동평균 교차) 하나뿐이며,
처음부터 실전 검증용 placeholder로 만들어진 것이다. 원래 로드맵(`PROCESSING.md`,
2026-09-06)에 "딥러닝 모델 연결"이 미착수 항목으로 남아 있었고, 2026-09-20
세션에서 이 작업을 시작하기로 했다.

**제약**: 검증된 실거래 데이터가 9/9(4,915틱, 5분)·9/10(약 2시간) 두 개뿐으로,
딥러닝 모델을 제대로 학습시키기엔 매우 적다. 이 설계는 그 사실을 전제로,
"모델 성능"이 아니라 "학습→저장→추론→신호→주문까지 배관이 끝까지 도는가"를
목표로 잡는다. 지금까지의 개발 방식(데이터 수집 → 전략 계수 보정 → 리스크
한도값)과 동일하게, 파이프라인을 먼저 끝까지 뚫고 품질은 데이터가 쌓인 뒤
다룬다.

## 목표

- 최근 N틱의 가격·거래량 시퀀스를 입력으로 받아 BUY/SELL/HOLD를 직접
  분류하는 소형 LSTM 모델을 학습하고, 그 결과를 실시간 파이프라인에
  `SignalPredictor` 구현체로 연결한다.
- 기존 `MovingAverageStrategy`는 건드리지 않는다 — 검증된 기본 전략을 유지한
  채, `--strategy` 플래그로 선택 가능한 대안을 추가한다.
- 학습 라벨링 시 미래 데이터가 과거 구간으로 새어 들어가는 데이터 누수를
  구조적으로 막는다(시간순 분리, lookahead 간격 확보).

## 비목표

- 모델 성능(수익성) 최적화 — 이번 범위 밖. 배관 검증이 목적.
- 기술적 지표(RSI/MACD 등) 기반 피처 가공 — 원시 가격/거래량만 사용.
- 호가창(매도/매수 호가) 정보 활용 — 이번 범위 밖.
- 모델 버전 레지스트리/A-B 서빙 — 단일 파일(`models/lstm_v1.pt`)로 충분.
- 하이퍼파라미터 탐색 자동화 — 합리적인 기본값으로 1회 학습.

## 아키텍처

```
[오프라인, 학습 시 1회]
data/ticks/*.jsonl (날짜별 녹화 파일)
   → 날짜별로 시간순 정렬 → 윈도우 구성(최근 N틱) → 정규화(수익률/로그거래량)
   → 라벨링(K틱 뒤 수익률 분포 기준 3분위 BUY/SELL/HOLD)
   → 날짜별 시간순 80/20 분리(train/val, 경계에 K틱 간격) → 합산
   → LSTM 학습 → models/lstm_v1.pt (가중치 + 정규화 기준값 + N/K 메타데이터)

[실시간, main.py --strategy lstm 실행 중]
KIS 틱 → LSTMStrategy.on_tick(tick)
   → 최근 N틱 버퍼(deque)에 추가 — 찰 때까지 HOLD (MovingAverageStrategy와 동일 패턴)
   → 버퍼 찼으면: 학습 때와 동일한 정규화 → torch 모델 forward(동기, CPU)
   → softmax 확률 최댓값을 strength로, 해당 클래스를 action으로 → Signal 반환
```

기존 `SignalPredictor` 프로토콜(`src/inference/worker.py`)이 이미
`on_tick(tick) -> Signal` 하나만 요구하므로, `LSTMStrategy`는 이 인터페이스만
만족하면 나머지 파이프라인(리스크 게이트, 주문 제출, 재생)을 전혀 건드리지
않고 그대로 재사용한다.

## 컴포넌트

### 1. `src/training/windowing.py` (신규)

순수 함수. 시간순 틱 리스트 → (윈도우, 라벨) 쌍 리스트로 변환.

- `build_windows(ticks, window_size)`: 슬라이딩 윈도우로 최근 `window_size`틱의
  (가격, 거래량) 시퀀스 추출.
- `normalize_window(window)`: 윈도우 시작가 대비 수익률로 가격 변환, 거래량은
  로그 스케일. 정규화 기준값(윈도우 시작가)은 추론 때도 동일하게 재현 가능해야
  하므로 이 함수가 유일한 정규화 경로가 된다(학습/추론 공유).
- `label_future_return(ticks, index, lookahead)`: index 시점에서 `lookahead`틱
  뒤 가격 수익률 계산 (구간을 벗어나면 `None` 반환 — 라벨링 불가 구간).
- `build_dataset(ticks, window_size, lookahead, thresholds)`: 위 함수들을 묶어
  (윈도우, 라벨) 데이터셋 생성. `thresholds`(상단/하단 분위값)는 별도로 계산해
  주입 — 이 함수는 라벨링 규칙만 적용하고 분위 계산은 하지 않는다(관심사 분리,
  분위 계산은 날짜별 병합 이후 전체 분포로 한 번만 해야 하므로).

### 2. `src/training/split.py` (신규)

- `chronological_split(ticks, val_ratio, lookahead)`: 시간순 앞 `1-val_ratio`를
  train, 뒤 `val_ratio`를 val로 분리하되, 경계에서 `lookahead`틱만큼 겹치는
  구간은 양쪽 다 제외(라벨 누수 방지).
- 날짜별 파일을 이 함수로 각각 분리한 뒤 train끼리, val끼리 합산.

### 3. `src/training/model.py` (신규)

- `LSTMClassifier(nn.Module)`: 입력 (batch, window_size, 2) → LSTM(hidden 16~32,
  1~2층) → 마지막 hidden state → Linear(3) → 클래스 3개(BUY/SELL/HOLD) 로짓.
- 실측 데이터 양이 매우 적으므로 hidden size/층 수는 작게 시작하고, dropout으로
  과적합을 최대한 억제한다.

### 4. `scripts/train_lstm.py` (신규)

CLI 진입점. `data/ticks/*.jsonl` 전체를 읽어 위 모듈들로 데이터셋 구성 →
학습 루프(합리적 기본 에폭/러닝레이트) → 검증셋 정확도 로그 출력 →
`models/lstm_v1.pt` 저장(가중치 state_dict + `{window_size, lookahead,
thresholds}` 메타데이터를 같은 체크포인트에 포함).

### 5. `src/strategies/lstm_strategy.py` (신규)

- `LSTMStrategy`: `SignalPredictor` 구현.
- 생성 시 `models/lstm_v1.pt` 로드(가중치 + 메타데이터), 심볼별 `deque(maxlen=N)`
  가격·거래량 버퍼 유지.
- `on_tick`: 버퍼 갱신 → 안 찼으면 `HOLD` 반환(strength 0.0) → 찼으면
  `windowing.normalize_window`로 학습과 동일하게 정규화 → 모델 forward →
  `Signal(action=argmax 클래스, strength=softmax 최댓값, ...)`.
- 모델 파일이 없으면 생성 시점에 명확한 에러로 즉시 실패(조용히 fallback하지
  않음 — 어떤 전략이 실제로 돌고 있는지 애매해지는 상황을 피함).

### 6. `src/main.py` 변경

- `--strategy {moving-average,lstm}` 인자 추가, 기본값 `moving-average`.
- 선택된 값에 따라 `_run_trading_loop`에 넘길 `predictor` 생성.

## 테스트 계획

- `tests/test_windowing.py`: 윈도우 구성, 정규화, 라벨링 — 특히 **경계 조건**
  (파일 끝 근처라 lookahead 구간이 없는 인덱스는 라벨 `None`)과 **정규화가
  윈도우 시작가만 기준으로 하고 이후 데이터를 참조하지 않는지**(데이터 누수
  아님을 보장) 검증.
- `tests/test_split.py`: 시간순 분리 경계에서 lookahead 간격만큼 양쪽 모두
  제외되는지, train/val에 같은 시점이 중복되지 않는지.
- `tests/test_lstm_strategy.py`: 실제 학습된 가중치 없이, 테스트에서 직접
  만든 아주 작은 더미 `LSTMClassifier`로 `LSTMStrategy`의 버퍼링·출력 형태만
  검증(모델 품질과 무관하게 배관이 맞는지).
- `scripts/train_lstm.py`는 유닛테스트 대상이 아니라, 합성 소량 데이터로
  "에러 없이 끝까지 실행되고 체크포인트 파일이 생성되는지"만 수동/1회성으로
  확인.

## 알려진 한계 (ponytail 주석으로 코드에도 명시)

- 지금 데이터 양(수천 틱)으로는 모델이 통계적으로 유의미한 예측력을 갖기
  어렵다. 이번 작업의 목적은 배관 검증이며, 실제 신호 품질은 검증하지 않는다.
- 업그레이드 경로: 자동 녹화가 몇 주~몇 달 쌓이면 `scripts/train_lstm.py`를
  더 큰 데이터로 재실행 — 코드 변경 없이 데이터 양만 늘려서 재학습 가능하도록
  설계됨.
- 라벨링 임계값(분위수 기준)은 학습 시점 데이터 분포에 의존적이라, 데이터가
  크게 달라지면(예: 다른 종목 추가) 재계산이 필요하다.
