# 진행 기록 (2026-09-22 세션 갱신) — 다음 세션 시작용

이전 기록: `PROCESSING.md`(2026-09-06 세션), `review.md`(감사 4라운드). 이 문서는 그 이후
2026-09-07 ~ 09-22 사이에 있었던 일과 **지금 상태, 다음에 할 일**만 정리한다.

## 한눈에 보는 현재 위치

| 단계 | 내용 | 상태 |
|---|---|---|
| 1단계 | 신호가 실제로 주문까지 이어지게 (전략 계수 보정) | 완료, `dev`에 머지됨 |
| 2단계 | 리스크 한도값 (MAX_ORDER_VALUE 100만 / MAX_DAILY_LOSS 10만 / 수량 1주 / MIN_SIGNAL_STRENGTH 0.60) | 값 그대로 유지하기로 결정, 변경 없음 |
| 3단계 | 딥러닝(LSTM) 신호 전략 연결 | 코드 완료, `dev`에 머지·푸시됨. 미니배치/정규화/임계값 분리 완료(9/22). 실데이터 재학습 전 |
| 4단계 | 종목별 수량, 지정가/목표가 매매 | 미착수 |

## 브랜치 머지 완료 (2026-09-21)

`lstm-signal-strategy`(8커밋, `a81ce1f`)를 `dev`에 `--no-ff`로 머지했다. 충돌 없음, 전체 테스트 **178개 통과**.
워크트리 `.worktrees/lstm-signal-strategy`와 브랜치는 삭제했다(9/21).
워크트리와 함께 `models/lstm_v1.pt`(gitignore)도 사라졌으니 `scripts/train_lstm.py`로 재학습해야 한다.
9/22에 `origin/dev`로 푸시 완료(`b93e0f0..6be5beb`).

## LSTM 리뷰 후속 조치 완료 (2026-09-22, `6be5beb`)

"다음에 할 일" 3번·4번 항목을 처리했다:

- **미니배치 도입**: `train.py`가 epoch당 풀배치 1스텝(총 30스텝)만 밟아 사실상 학습이 안 되던 문제. `torch.utils.data.DataLoader`로 셔플된 미니배치를 도입(`run_training(..., batch_size=64)`, `scripts/train_lstm.py --batch-size`).
- **채널별 정규화**: `normalize_window`가 가격 수익률(±0.001대)과 `log1p(거래량)`(2~9대)를 그대로 섞어써서 거래량 채널이 입력을 지배하던 문제. 두 채널을 윈도우 단위로 각각 z-score 정규화하도록 변경(`src/training/windowing.py`). 학습/추론(`lstm_strategy.py`)이 같은 순수 함수를 쓰므로 드리프트 없음.
- **전략별 `MIN_SIGNAL_STRENGTH` 분리**: `RiskGate`에 `min_signal_strength_by_strategy` 옵션 추가, `order.strategy_id`로 임계값을 오버라이드. `Settings.min_signal_strength_lstm`(env `MIN_SIGNAL_STRENGTH_LSTM`, 미설정 시 `MIN_SIGNAL_STRENGTH`와 동일값 — 동작 변화 없음)를 `"lstm"` 전략에 연결(`src/application.py`).

테스트 179개 전체 통과. 기존 체크포인트 포맷(7개 키)은 변경 없음 — 재학습만 하면 새 정규화가 자동 반영됨.

## LSTM 전략 — 무엇이 만들어졌나

- 스펙: `docs/superpowers/specs/2026-09-20-lstm-signal-strategy-design.md`
- 계획: `docs/superpowers/plans/2026-09-20-lstm-signal-strategy.md`
- `src/training/windowing.py` — 윈도우 구성, 정규화(가격은 윈도우 시작가 대비 수익률, 거래량은 log1p, 두 채널 모두 윈도우 단위 z-score — 9/22 변경), 미래 수익률 기반 라벨링. `LABEL_SELL=0, LABEL_HOLD=1, LABEL_BUY=2`는 여기에서만 정의.
- `src/training/split.py` — 시간순 train/val 분리(경계에 lookahead 간격, 섞지 않음).
- `src/training/model.py` — 소형 `LSTMClassifier`(hidden 16, 1층).
- `src/training/train.py` — `run_training(...)`. 파일·종목별로 따로 분리하고, 라벨 임계값(분위수)은 train 쪽 수익률로만 계산(누수 방지).
- `scripts/train_lstm.py` — CLI 진입점. 기본 glob은 `data/ticks/ticks_[0-9]*.jsonl`(테스트용 `ticks_test_*` 제외).
- `src/strategies/lstm_strategy.py` — `LSTMStrategy`(`on_tick(tick) -> Signal`). 체크포인트가 없으면 생성 시점에 `FileNotFoundError`.
- `src/main.py` — `--strategy {moving-average,lstm}`(기본 moving-average). LSTM은 선택했을 때만 import(torch 지연 로딩).
- 체크포인트 키 7개: `state_dict, window_size, lookahead, low_threshold, high_threshold, hidden_size, num_layers`. 추론 쪽은 앞의 4개 중 `state_dict/window_size/hidden_size/num_layers`만 읽는다(나머지는 학습 기록용으로 의도적).

첫 학습 결과(9/9 + 9/10 녹화, 수정 전 코드): `train_size=63867 val_size=15934 val_accuracy=0.425`.
`--replay`로 스모크 테스트 시 신호 강도 0.39~0.40으로 전부 리스크 게이트(0.60)에서 거부 — 예상된 결과.
스펙이 이미 "데이터 부족으로 성능은 무의미할 수 있음, 이번 목표는 배관 검증"이라고 명시했다.

## 이번 기간에 고친 것 (`dev`에 반영됨)

- `949041c`, `9bca13f`, `a1256a0` — KIS H0STCNT0 파싱. 진짜 원인은 필드 구분자가 `|`가 아니라 `^`였던 것. 이후 KIS가 레코드 폭을 46→47필드로 무통보 변경해서, 폭을 하드코딩하지 않고 `len(fields)//count`로 계산하도록 수정.
- `662a3f8` — `queue.publish()` 실패 1건이 수집 세션 전체를 죽이지 않게. (원인: Windows용 Redis 5.0.14.1의 BGSAVE fork 크래시)
- `920989b` — 장 마감 15:30 → 20:00.
- `00478dc` — `--replay-speed`(배속 재생). 퇴근 후 하루치를 몇 분에 재생해서 튜닝하려는 용도.
- `6a89c6a` — `MovingAverageStrategy` 강도 계수 20→300(`strength_gain`). 실데이터에서 강도가 0.507을 못 넘던 문제 해결, 재생 시 6건 승인 확인.

## 시스템 설정 변경 (git에 안 남는 것 — 잃어버리면 다시 해야 함)

- Redis: `tools/redis/redis.windows-service.conf`에서 `save ""`(RDB 자동 저장 끔) + 실행 중 서버에도 `CONFIG SET`. `tools/`는 gitignore.
- 작업 스케줄러: `StockRecordStart`/`StockRecordStop`을 `LogonType=S4U`로 변경(로그인 상태 무관 실행). `StockRecordStop`은 20:05로 이동. 둘 다 관리자 권한으로 사용자가 직접 실행함.
- 작업 스케줄러 Operational 이벤트 로그 활성화(`wevtutil sl Microsoft-Windows-TaskScheduler/Operational /e:true`).
- 전원: AC 전원일 때 대기 모드 진입 시간 0(안 잠). `powercfg /change standby-timeout-ac 0`.

## 환경 주의사항 (이번에 실제로 겪은 것)

- 경로에 한글(`10_교육`)이 있어서 **PowerShell/cmd 기반 서브에이전트가 실패**한다(Task 5 첫 시도가 파일 0개 만들고 성공했다고 보고). 서브에이전트에게는 Bash 툴만 쓰라고 명시할 것. Bash에서는 경로를 `/`로 쓸 것(`\`는 이스케이프로 먹힘).
- 서브에이전트 보고를 그대로 믿지 말고 `git log`, `git status`, `pytest`를 컨트롤러가 직접 한 번 확인할 것. (Task 5에서 이 확인이 잘못된 보고를 잡았다.)
- venv는 메인 체크아웃 것을 절대경로로 공유: `D:\BACKUP\10_교육\works\Stock\.venv\Scripts\python.exe`. 워크트리에서 pytest는 워크트리 cwd에서 실행.
- `data/`는 gitignore라서 **워크트리에는 없다**. 학습하려면 메인 체크아웃의 `data/ticks/ticks_*.jsonl`을 복사해야 한다.
- `models/lstm_v1.pt`도 gitignore이고 현재 없다(워크트리와 함께 삭제됨). `python scripts/train_lstm.py`로 다시 만들 수 있다.
- `tests/test_main.py::test_main_record_mode_lets_trading_loop_read_ticks`가 전체 스위트에서 가끔 실패(단독/재실행은 통과) — 기존 타이밍 flake로 판단, 이번 변경과 무관.

## 자동 수집 상태 (미해결 포함)

- 파싱·Redis 문제는 해결됐고 9/9(4,915틱), 9/10(약 2시간)만 정상 녹화본이 있다.
- 9/11, 9/14, 9/15: 로그온 방식 문제로 08:55 트리거가 조용히 안 돎 → S4U로 수정.
- 9/16: 트리거가 08:55가 아니라 12:13에 실행(Modern Standby로 지연 추정) → 대기 모드 끔으로 조치. 그날은 실행 중이던 프로세스가 수정 전 코드를 쓰고 있어서 파싱 전멸, 녹화 0건.
- 9/17: 로그가 22:40에 시작(장 마감 후), 틱 파일 없음, 9/18 19:07에 DNS 실패로 종료. 9/18(금)은 로그 자체가 없음.
- **9/21(월) 검증 결과**: 대기 모드 끈 뒤 처음으로 `StockRecordStart`가 08:55:00에 정시 실행(결과 0, 놓친 실행 0). `ticks_20260921.jsonl` 301,612줄(약 40MB, 09:00~18:43 KST), `unparseable` 0건, `errors=0`. 정규장 전체 수집 성공.
- 9/21 18:44:02에 수집기가 종료됨(20:00 마감 전 약 76분 누락). 원인: `/oauth2/Approval` 요청의 DNS 실패(`getaddrinfo failed`)가 `approval_key()`에서 `KISWebSocketError`로 올라왔는데 재시도 대상 예외에 없어서 즉시 종료. 9/18의 DNS 종료도 같은 원인으로 보임.
- **수정(9/21)**: `stream()` 재시도 대상에 `KISWebSocketError` 추가, 백오프 상한 60초, 재시도 경고 로그, `main.py`에서 `max_reconnects=30`(약 25분 장애 허용). 회귀 테스트 추가. **내일(9/22) 08:55 실행분부터 새 코드가 적용되는지, 그리고 실제 DNS 장애 시 재시도 로그가 남는지 확인 필요.**

## 다음에 할 일 (우선순위 순)

1. ~~브랜치 머지~~ 완료(9/21). ~~푸시~~ 완료(9/22, `6be5beb`).
2. ~~9/21(월) 자동 수집 확인~~ 완료. ~~9/22 수집 확인~~ 완료 — errors=0, cycles 정상 증가, DNS 재시도 수정 반영 상태로 19:30까지 정상 수집 확인. 20:00 마감까지 살아있었는지는 다음 세션에서 최종 로그로 재확인.
3. ~~`train.py` 미니배치 도입~~ 완료(9/22). ~~가격/거래량 정규화~~ 완료(9/22).
4. ~~`MIN_SIGNAL_STRENGTH` 전략별 분리~~ 완료(9/22, `RiskGate.min_signal_strength_by_strategy` + `MIN_SIGNAL_STRENGTH_LSTM`).
5. **다음 순서**: 실제 데이터(9/9, 9/10, 9/21, 9/22)가 쌓였으니 `scripts/train_lstm.py`로 재학습 → val_accuracy가 이전(0.425)보다 나아졌는지 확인.
6. LSTM 스모크 테스트는 리스크 게이트까지만 갔고 주문 관리자까지는 안 갔다(전부 거부됨). 재학습 후 임계값을 낮춰서 한 번 더 돌려 마지막 구간을 확인.
7. 4단계(종목별 수량, 지정가/목표가 매매).

## 리뷰에서 보류한 사소한 항목

- `train.py`: `all_train_returns`가 비면 `np.quantile`이 예외(입력 파일이 너무 짧을 때).
- `lstm_strategy.py`: 손상된 체크포인트에서 `KeyError`(설명 없는 오류), `torch.load`에 `weights_only=True` 미적용.
- `windowing.py`: `build_dataset`의 `.reshape`는 사실상 불필요, `low_threshold < high_threshold` 검증 없음.
- `tests/test_split.py` 주석의 "6 points"는 실제 4개(주석 오타, 단언은 정확).

## 자주 쓰는 명령

```powershell
cd "D:\BACKUP\10_교육\works\Stock"
.\.venv\Scripts\python.exe -m pytest -q                       # 179개 (미니배치/정규화/전략별 임계값 반영 후)
.\.venv\Scripts\python.exe scripts\train_lstm.py --batch-size 64   # data/ticks/ticks_[0-9]*.jsonl로 학습
.\.venv\Scripts\python.exe -m src.main 005930 --replay data\ticks\ticks_YYYYMMDD.jsonl --replay-speed 60 --status-interval 0
.\.venv\Scripts\python.exe -m src.main 005930 --strategy lstm --replay data\ticks\ticks_YYYYMMDD.jsonl --replay-speed 60 --status-interval 0
```
