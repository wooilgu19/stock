# 진행 기록 (2026-09-30 세션 갱신) — 다음 세션 시작용

이전 기록: `PROCESSING.md`(2026-09-06 세션), `review.md`(감사 4라운드). 이 문서는 그 이후
2026-09-07 ~ 09-30 사이에 있었던 일과 **지금 상태, 다음에 할 일**만 정리한다.

## 한눈에 보는 현재 위치

| 단계 | 내용 | 상태 |
|---|---|---|
| 1단계 | 신호가 실제로 주문까지 이어지게 (전략 계수 보정) | 완료, `dev`에 머지됨 |
| 2단계 | 리스크 한도값 (MAX_ORDER_VALUE 100만 / MAX_DAILY_LOSS 10만 / 수량 1주 / MIN_SIGNAL_STRENGTH 0.60) | 값 그대로 유지하기로 결정, 변경 없음. 9/29~30 실거래 로그에서 `daily loss limit has been reached` 거부가 처음 발동 확인 |
| 3단계 | 딥러닝(LSTM) 신호 전략 연결 | 코드 완료, `dev`에 머지·푸시됨. 미니배치/정규화/임계값 분리 완료(9/22). 9/23~24에 검증·라벨 결함 2건 발견·수정. **9/28에 6일치로 첫 신뢰 가능한 결과**(`val_accuracy=0.580`, 기준선 0.500 상회) — 재현성 확인 전 |
| 종목 선정 | 거래대금 순위 API 기반 일일 스크리너(`src/screener.py`) → 수집기 연결 | 구현 완료(9/24). 9/28~29 이틀 연속 005930 단독 폴백 발생 → 원인 규명·수정(9/29) → **9/30 relaxed 필터 작동 확인, 그러나 새 문제 발견**(장전 데이터 품질) — 아래 참고 |
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

## 2026-09-23~24 작업 (커밋 전 — `git status` 확인)

### 1. LSTM 검증/라벨 결함 2건 발견·수정

9/23에 5일치(9/9, 9/10, 9/21, 9/22, 9/23)로 처음 재학습했더니 `val_accuracy=0.870`. 목표(0.45~0.50)를 훌쩍 넘어 의심스러워 원인을 추적했다.

- **결함 A — 같은 날 안에서 train/val 분할**: `train.py`가 파일(하루)마다 따로 앞 80%/뒤 20%로 나눠서, 검증 구간이 그날 추세의 연장이었다. → **날짜 단위 holdout**으로 변경. 파일이 2개 이상이면 가장 최근 `round(파일수 × val_ratio)`일(최소 1일, 학습용 최소 1일 보장)을 통째로 검증에 쓴다. 파일이 1개일 때만 기존 `chronological_split`로 되돌아간다. 그래도 `val_accuracy=0.832`.
- **결함 B — 라벨 임계값 붕괴(진짜 원인)**: 틱의 72.5%가 직전 틱과 같은 가격(처음 2,000틱에 가격 종류 5개)이라 lookahead=5틱 뒤 수익률이 대부분 0. 30%/70% 분위수가 둘 다 `0.0`이 됐고, 라벨 조건이 `>=`/`<=`라서 수익률 0이 전부 BUY/SELL로 분류됐다. 검증 라벨은 BUY 81%·SELL 19%·HOLD 0%였고, **"항상 BUY"만 찍어도 81.5%인데 모델은 83.2%** — 학습된 실력은 사실상 없었다.
- **수정**: `windowing.py` 라벨 비교를 `>`/`<`로 바꿔 수익률 0은 HOLD. `scripts/train_lstm.py` lookahead 기본값 5 → **300틱**. 학습 결과에 `val_label_counts(sell,hold,buy)`와 `majority_baseline`을 함께 출력해서, 앞으로는 val_accuracy를 다수 클래스 기준선과 항상 같이 본다.
- 테스트 181개 통과. 재학습은 세션 종료로 두 번 중단(9/23분, 9/24분 모두 결과 없음) 후 **9/28에 6일치(9/9, 9/10, 9/21~23, 9/28)로 성공**: `train_size=837573 val_size=268867 val_accuracy=0.580`, `val_label_counts(sell,hold,buy)=[73275, 134403, 61189]`, `majority_baseline=0.500`. 목표(0.45~0.50) 상회, 다수 클래스 기준선도 8%p 상회, 라벨 분포도 세 클래스 고르게 분산 — 처음으로 믿을 만한 결과. `models/lstm_20260928.pt`. 다만 2단계 기준은 "재현 안정성"도 요구하므로 1회 결과만으로는 미완 — 재현 확인 필요.
- 교훈: val_accuracy 숫자 하나로 판단하지 말 것. 라벨 분포와 다수 클래스 기준선을 먼저 본다.

### 2. 일일 종목 스크리너 (`src/screener.py`)

- 배경: 삼성전자 1종목만 수집·학습해서 다른 종목 일반화가 검증되지 않음. 매매 종목을 그날그날 골라야 함.
- GitHub의 공개 스크리너(pykrx/FinanceDataReader 기반, 대부분 장 마감 후 일봉 방식)는 실시간 선정에 안 맞아 **KIS 순위 API를 직접 사용**하기로 결정.
- API: 거래량순위 `/uapi/domestic-stock/v1/quotations/volume-rank` (`FHPST01710000`, 거래금액순, 최대 30건). 등락률순위(`FHPST01700000`)와 조건검색(`psearch-*`, HTS 조건 저장 필요·조건당 100건)도 조사했으나 미사용 — 등락률순위는 거래가 얇은 급등주를 끌어오고(필터 없이 부르면 신규상장 ETN +280%가 섞임), 응답에 이미 현재가·등락률이 있어 호출 1번이면 충분.
- 선정 규칙: ETF·ETN·우선주·관리·거래정지·SPAC 등 제외 플래그(`1111111111`) → 현재가 ≥ 1,000원, 등락률 절댓값 1~15%(상한가 추격 방지) → 거래대금 상위 5개.
- `KISRestClient.get(path, tr_id, params)` 공개 메서드 추가(인증 헤더 포함). `python -m src.screener`는 종목코드를 공백 구분으로 stdout에, 상세는 stderr에 출력.
- 실서버 호출로 확인: 삼성전자·SK하이닉스·SK스퀘어·삼성전기·두산에너빌리티가 선정, ETF는 제외됨.
- **`.env`의 `KIS_BASE_URL`이 실서버(`openapi.koreainvestment.com:9443`)** 다. 주문은 로컬에서 `simulated`로만 기록되고 KIS로 안 나간다. 모의투자 서버(`openapivts`)에서 순위 API가 되는지는 미확인.

### 3. 수집 스크립트 연동 (`scripts/record_market_open.ps1`)

- 08:55에 스크리너 실행 → `005930`(데이터 연속성용 고정) + 선정 종목을 수집기 인자로 전달. 스크리너가 실패하거나 출력 형식이 이상하면 `005930`만으로 수집. 선정 결과는 그날 로그에 `screener symbols=...`로 기록.
- **KIS 접근토큰은 앱키당 1분에 1회**(`EGW00133`, 403). 스크리너와 수집기는 별도 프로세스라 각자 토큰을 발급하므로, 스크리너 후 `Start-Sleep 65`를 넣었다(수집 시작이 08:56쯤으로 밀림). 토큰을 디스크에 캐시하면 이 대기를 없앨 수 있음(미구현).
- 수집 종료 후 **0바이트 틱 파일은 삭제**. 휴장일에도 스케줄러가 돌아 빈 파일이 생기면, 가장 최근 날짜라서 검증일로 잡혀 학습이 깨지기 때문.
- 08:55 시점 순위는 전일 거래 기준일 가능성이 큼(미확인). 종목 5개면 틱 저장량과 매매 루프 부하가 늘어남.

### 4. 휴장 일정과 스케줄러 상태

- 9/24(목)·9/25(금) 추석 연휴 휴장, **다음 개장일은 9/28(월)**(9/28은 대체공휴일 아님으로 보도됨 — 월요일 아침 로그로 최종 확인).
- `StockRecordStart`는 9/23 이후 9/24분이 실행되지 않았고 다음 실행이 9/25 08:55로 잡혀 있음(원인 미확인, 휴장일이라 영향 없음).
- 9/23은 18:37까지 수집(틱 223,772줄).

## 2026-09-29~30 작업

### 스크리너 08:55 폴백 원인 규명·수정

9/28, 9/29 이틀 연속 스크리너가 `005930` 단독으로 폴백됨(`screener symbols=005930`).
원인 추정: 08:55(정규장 시작 5분 전)엔 전일대비 등락률이 거의 모든 종목에서 0%에
가까워, `select_symbols`의 등락률 필터(`min_change_pct=1.0`)를 통과하는 종목이 없음.

- `select_daily_symbols()` 추가(`src/screener.py`): strict 필터(등락률 1~15%)가
  빈 결과면 등락률 조건만 뺀 relaxed 필터로 재시도.
- `record_market_open.ps1`이 스크리너 stderr를 더 이상 버리지 않고(`2>$null` 제거)
  그날 로그에 남기도록 수정 — 후보 수, strict/relaxed 어느 티어로 뽑혔는지 기록.
  PowerShell이 네이티브 프로세스 stderr를 깨뜨리는 문제 때문에 cmd.exe로 우회(수집기와
  동일한 방식).
- 테스트 183개 통과.

**9/30 08:55 로그로 확인**: `fetched 30 candidates, picked 5 via relaxed(min_change_pct=0) filter`.
원인 추정이 맞았고 relaxed 폴백도 정상 동작.

**그런데 relaxed 결과 자체가 새 문제를 보여줌**: 선정된 5종목의 거래대금이 0~3억
수준(009830, 001820, 089030, 036930, 403870)으로, 장 마감 후 같은 API로 확인한
거래대금 상위 종목(수천~수만억, 예: SK하이닉스 5조)과 비교가 안 될 만큼 작다. 즉
**08:55 시점의 "거래금액순 30건" 자체가 그날 실제 유동성 상위 종목과 무관한 목록으로
보인다**(장 시작 전 지표라 의미가 다를 가능성). `005930`은 고정 종목이라 항상
포함되지만, 스크리너가 고른 나머지는 유동성이 사실상 없는 종목일 수 있음 — **미해결,
다음에 할 일 참고**.

## LSTM 실전 전환 기준 (2026-09-22 정리)

"언제 실전으로 넘어가나"에 정해진 날짜는 없다. 아래 4단계를 순서대로 통과해야 한다.
현재는 정상 녹화일이 9/9·9/10(부분)·9/21·9/22·9/23·9/28·9/29·9/30 8일이라 **1단계에도 아직 못 미친다**(목표 15~20일의 절반 수준). 2단계는 9/28에 6일치로 처음 신뢰 가능한 결과(`val_accuracy=0.580`, 기준선 0.500 상회, 라벨 분포 정상)가 나왔으나 **재현성(재학습할 때마다 안정적으로 나오는지) 미확인** — 위 "2026-09-23~24 작업" 참고.

1. **데이터 양** — 정규장 최소 15~20일(약 3~4주) 분량. 하루 약 30만 틱이면 종목당 윈도우가
   수만~수십만 개 나오지만, 상승/하락/횡보 장세가 섞여야 특정 하루 패턴에 과적합되지 않는다.
2. **검증 정확도** — `chronological_split` 기준 시간순 분리 validation accuracy가 3클래스
   무작위 추측(0.333)보다 확실히 높고(목표: 0.45~0.50 이상), 재학습할 때마다 안정적으로
   재현되어야 한다. 첫 학습 결과 `val_accuracy=0.425`(9/9+9/10, 수정 전 코드)는 아직 이 기준
   미달로 취급한다 — 한 번 나온 숫자로 판단하지 않는다.
3. **리스크 게이트 통과 여부** — `--replay`로 여러 날짜에 걸쳐 승인 주문이 꾸준히 나오는지
   확인. 지금까지 스모크 테스트는 강도가 임계값 근처도 못 가서 전부 거부됐다.
4. **모의투자 실전 검증** — 위 세 단계를 통과한 뒤 `--strategy lstm`으로 실시간 paper trading을
   최소 2~4주 추가로 돌려 실시간 추론 지연, 리스크 게이트 동작, 실제 손익(승률뿐 아니라
   낙폭)까지 확인한다.

이 네 단계를 모두 통과한 뒤에만 `KIS_ENV=live` 전환을 검토하고, 전환하더라도
`MAX_ORDER_VALUE`/`MAX_DAILY_LOSS`/수량 1주 설정을 그대로 유지한 채 소액으로 시작한다.

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
- **미적용 — 조치 필요**: `StockRecordStart`/`StockRecordStop` 둘 다 `StartWhenAvailable=False`라서, 트리거 시각에 PC가 꺼져있거나 절전이면 나중에 켜져도 그 실행을 건너뛴다. 9/25(추석 연휴) 20:05에 이 문제로 `StockRecordStop`이 안 돌아, 9/25 08:55에 시작된 수집 프로세스가 9/27 22:35(DNS 오류로 자멸)까지 3일간 떠 있었다(Task Scheduler Operational 로그 이벤트 153, "did not launch task ... as it missed its schedule"). 휴장일이라 실제 피해는 없었음. 관리자 PowerShell에서 아래로 고칠 것(에이전트는 권한 거부로 실행 불가, 사용자가 직접):
  ```powershell
  $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
  Set-ScheduledTask -TaskName StockRecordStop -Settings $settings
  Set-ScheduledTask -TaskName StockRecordStart -Settings $settings
  ```

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
5. ~~`scripts/train_lstm.py` 재학습(날짜 holdout + 라벨 수정 + lookahead 300)~~ 완료(9/28) — `val_accuracy=0.580`, `majority_baseline=0.500`, 라벨 분포 SELL 27%/HOLD 50%/BUY 23%로 정상. **다음 순서**: 시드·데이터 구성을 바꿔 1~2회 더 재학습해서 재현성(0.55~0.60대 안정적으로 재현) 확인.
5-1. ~~9/28(월) 08:55 실행 확인~~ 완료 — 스크리너가 `005930` 단독 폴백(9/28, 9/29). 원인 규명·수정(9/29)·검증(9/30) 완료, 아래 8번 참고.
5-2. **작업 커밋 필요**: 9/23~30 변경(스크리너 + relaxed 폴백 + 로깅, 날짜 holdout, 라벨 수정, ps1, 문서) 전체가 아직 커밋 전.
5-3. 다종목 수집이 안정되면 종목 혼합 학습 시 라벨 임계값(분위수)을 종목별로 볼지 검토. 과거 분봉 API로 데이터를 채우는 방안은 KIS 조회 기간 제한 확인 후 결정(틱 모델과 입력 분포가 달라지는 점 주의).
6. LSTM 스모크 테스트는 리스크 게이트까지만 갔고 주문 관리자까지는 안 갔다(전부 거부됨). 재학습 재현성 확인 후 임계값을 낮춰서 한 번 더 돌려 마지막 구간을 확인.
7. 4단계(종목별 수량, 지정가/목표가 매매).
8. **스크리너 장전 데이터 품질 문제(신규, 9/30 발견)**: relaxed 폴백은 동작하지만, 08:55 시점 "거래금액순 30건" 자체가 장 마감 후 같은 API로 보는 실제 유동성 상위 종목과 무관해 보임(9/30 선정 5종목 거래대금이 0~3억으로, 실제 상위 종목의 수천~수만억과 비교 불가). 다음 중 하나로 방향을 정해야 함: (a) 스크리너 실행 시각을 09:05~09:10 등 정규장 시작 후로 늦추기(수집 시작이 그만큼 늦어짐), (b) 전일 종가 기준 거래대금 순위로 대체할 API 확인, (c) 지금처럼 005930 고정 + 부가 종목은 그날그날 품질 편차를 감수. 사용자 결정 필요.
9. **일일 손실 한도 발동 확인(신규, 9/29~30 발견)**: 로그에 `daily loss limit has been reached` 거부가 반복적으로 나타남. `RiskGate`의 의도된 동작인지, 임계값(`MAX_DAILY_LOSS` 10만)이 지금 종목 수(6개)에 비해 너무 타이트한지 검토 필요 — 아직 원인 조사 전.

## 리뷰에서 보류한 사소한 항목

- `train.py`: `all_train_returns`가 비면 `np.quantile`이 예외(입력 파일이 너무 짧을 때).
- `lstm_strategy.py`: 손상된 체크포인트에서 `KeyError`(설명 없는 오류), `torch.load`에 `weights_only=True` 미적용.
- `windowing.py`: `build_dataset`의 `.reshape`는 사실상 불필요, `low_threshold < high_threshold` 검증 없음.
- `tests/test_split.py` 주석의 "6 points"는 실제 4개(주석 오타, 단언은 정확).

## 자주 쓰는 명령

```powershell
cd "D:\BACKUP\10_교육\works\Stock"
.\.venv\Scripts\python.exe -m pytest -q                       # 181개 (스크리너 테스트 포함)
.\.venv\Scripts\python.exe scripts\train_lstm.py --batch-size 64   # data/ticks/ticks_[0-9]*.jsonl로 학습 (마지막 날 통째로 검증, lookahead 기본 300)
.\.venv\Scripts\python.exe -m src.screener                         # 오늘의 선정 종목 출력 (토큰 발급 1분당 1회 주의)
.\.venv\Scripts\python.exe -m src.main 005930 --replay data\ticks\ticks_YYYYMMDD.jsonl --replay-speed 60 --status-interval 0
.\.venv\Scripts\python.exe -m src.main 005930 --strategy lstm --replay data\ticks\ticks_YYYYMMDD.jsonl --replay-speed 60 --status-interval 0
```
