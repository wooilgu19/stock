# 진행 기록 (2026-09-06 세션)

다음 세션에서 이어서 개발할 때 참고용. 이 세션에서 한 일, 지금 상태, 아직 안 된 것,
다음에 시작할 때 체크리스트 순서로 정리. (이전 세션 기록은 git log와 `review.md`에
남아있음 — 8/16 세션 이후 약 3주 공백 후 이어서 진행.)

## 이 세션에서 한 일

### 1. 체크리스트 재검증
3주 공백 후 pytest(125개 통과) / `validate-config --live` / Redis ping 셋 다
문제없이 통과 — 지난 세션 종료 시점과 동일한 상태로 확인됨.

### 2. 틱 녹화/재생 기능 설계·구현 — 야간·주말 실전 관찰용
평일 장중에만 실전 시세로 파이프라인을 관찰할 수 있었던 문제를 해결하기 위해,
평일에 녹화한 실시간 틱을 야간/주말에 원래 속도로 재생해서 신호·리스크게이트·주문
로직을 그대로 관찰할 수 있게 만듦. `superpowers` 스킬(brainstorming →
writing-plans → subagent-driven-development)로 설계 문서, 구현 계획, 5개 태스크
구현 + 리뷰 + 최종 전체 리뷰까지 전 과정 진행.

- 스펙: `docs/superpowers/specs/2026-09-06-tick-record-replay-design.md`
- 계획: `docs/superpowers/plans/2026-09-06-tick-record-replay.md`
- 브랜치 `tick-record-replay`(워크트리에서 작업) → `dev`에 fast-forward 머지 완료
  (커밋 `776f258`~`fc8da7a`, 이후 최종 리뷰 fix wave `0c6e0ba`, `5bbd0e6`)

**구현된 것:**
- `src/queue/recording_queue.py` — `RecordingQueue`: 큐를 감싸서 publish할 때마다
  JSONL 파일에도 기록. `__getattr__`로 `.read()`/`.ping()` 등 다른 메서드는
  내부 큐에 위임(최종 리뷰에서 이게 빠져서 `--record` 시 매매 루프가 조용히
  멈추는 치명적 버그를 발견 → 수정).
- `src/replay.py` — `replay_ticks()`: 녹화 파일을 읽어 원래 시간 간격대로
  재생하며 큐에 publish. 빈 파일/깨진 파일은 즉시 `ValueError`.
- `src/application.py` — `build_order_manager`/`build_pipeline`/`build_runtime`에
  `enforce_market_hours` 플래그 추가. 재생 시 실제 벽시계 기준 장시간 체크를
  꺼서, 과거 장중 데이터를 밤에 재생해도 주문이 거절되지 않게 함.
- `src/main.py` — `--record <path>` / `--replay <path>` CLI 플래그.
  - `--replay`는 KIS 인증 불필요. 단, **최종 리뷰에서 발견한 안전장치**로
    `PAPER_TRADING=false`(실거래 모드)일 때 `--replay`를 쓰면 즉시 거부하도록
    수정함 — 안 그러면 과거 시세로 실계좌에 진짜 주문이 나갈 수 있었음.
  - `--record`와 `--replay` 동시 사용은 시작 시점 에러.
- `development.md`에 사용법 문서화.

**테스트:** 125 → 141개로 증가, 전부 통과.

**과정에서 배운 것 (중요):** 태스크별 리뷰는 각 조각이 개별적으로는 맞다고
승인했지만, 최종 전체 리뷰에서만 드러난 통합 버그가 2건(Critical) 있었음 —
`RecordingQueue`가 `read()`를 위임하지 않아 `--record` 모드가 사실상 매매를
멈추는 문제, 그리고 `--replay` + 실거래 모드 조합의 안전 문제. 둘 다 fix wave로
해결하고 재검토까지 클린 확인.

### 3. 평일 장중 자동 녹화 스케줄링 (Windows 작업 스케줄러)
사용자가 직장에 있어 평일 장중에 직접 노트북을 조작할 수 없다는 제약 때문에,
무인 자동 실행 인프라를 구성함.

- `scripts/record_market_open.ps1` — 평일 08:55에 `--record`로 005930 틱을
  `data/ticks/ticks_YYYYMMDD.jsonl`에 녹화 시작, 로그는
  `logs/record_YYYYMMDD.log`.
- `scripts/stop_record.ps1` — 16:00에 실행되는 안전장치. KIS가 장마감 후
  세션을 끊으면 재연결 소진으로 프로세스가 스스로 종료되긴 하지만
  (`src/api/kis_websocket.py`), 혹시 남아있을 경우를 대비.
- `scripts/README.md`에 등록/해제/종목변경 방법 정리.
- Windows 작업 스케줄러에 `StockRecordStart`(평일 08:55), `StockRecordStop`
  (평일 16:00) 두 작업 등록 완료 — 로그인 상태(화면 잠금 무관)일 때만 실행됨.

**구성 중 발견/수정한 버그 2건 (검증 완료):**
1. PowerShell 5.1이 BOM 없는 UTF-8 스크립트의 한글 경로("10_교육")를
   깨뜨려서 `Set-Location` 실패 → BOM 포함 UTF-8로 재저장.
2. PowerShell이 파이썬 stderr 로그를 자체 ErrorRecord로 감싸서 로그가
   깨지고 스크립트가 중간에 죽음 → 실제 실행 부분을 `cmd.exe`로 우회.

`Start-ScheduledTask`로 강제 트리거 → 로그 정상 기록 확인 →
`stop_record.ps1`로 정상 종료까지 실제로 검증함(장이 닫혀있어 실제 틱 수신은
확인 못 함, 배관 자체만 검증).

## 지금 상태 (검증됨)

- 테스트: **141개 전부 통과**
- `dev` 브랜치에 전부 머지됨, `origin/dev`로는 아직 push 안 함(로컬이 60커밋 앞섬)
- Windows 작업 스케줄러: `StockRecordStart`/`StockRecordStop` 등록 및 수동
  트리거 검증 완료. 다음 평일(2026-09-07 월) 08:55에 자동 실행 예정.
- 노트북은 켜진 채로, "SDS" 계정 로그인 상태(화면 잠금 무관) 유지 필요.

## 아직 안 된 것

1. **평일 장중 실전 관찰 — 자동 녹화 결과 확인 (최우선)**: 다음 평일 장 마감
   후(또는 그 다음날), `data/ticks/ticks_YYYYMMDD.jsonl`과
   `logs/record_YYYYMMDD.log`를 같이 확인하고, `--replay`로 재생해서 신호가
   실제로 뜨는지 관찰. 이게 이번 세션 작업의 목적.
2. **위험 한도값 검토** — `.env`의 `MAX_ORDER_VALUE`, `MAX_DAILY_LOSS`,
   `MIN_SIGNAL_STRENGTH` 기본값 그대로. 사용자 투자 규모에 맞게 조정 필요.
3. **KIS 실제 모의투자(VTTC) 계좌 연동 배선** — 미착수 (이전 세션과 동일).
4. **딥러닝 모델 연결** — 미착수, 별도 세션 필요 (이전 세션과 동일).
5. **종목별 다른 수량 설정, 지정가/목표가 매매** — 미착수 (이전 세션과 동일).
6. **재생 반복 시 중복 페이퍼 거래** — 같은 녹화 파일을 두 번 재생하면 동일한
   틱 시각 기반 주문ID로 중복 기록됨. 관찰용이라 당장 문제는 아니지만,
   반복 재생 시 `DATABASE_PATH`를 스크래치용으로 바꿔 쓰는 걸 권장
   (`development.md`에 이미 안내됨).
7. Task 2~4 최종 리뷰에서 deferred로 남긴 사소한 항목들 —
   `docs/superpowers/plans/2026-09-06-tick-record-replay.md` 참고
   (모두 낮은 위험으로 판단, 당장 조치 불필요).

## 다음 세션 시작할 때 체크리스트

```powershell
cd "D:\BACKUP\10_교육\works\Stock"
.\.venv\Scripts\Activate.ps1
python -m pytest -q                          # 141개 통과하는지 먼저 확인
python -m src.cli validate-config --live      # .env 아직 유효한지 확인
python -c "from src.queue.redis_queue import RedisQueue; RedisQueue().ping(); print('redis ok')"
Get-ScheduledTaskInfo -TaskName "StockRecordStart" | Select-Object LastRunTime, LastTaskResult
```

마지막 줄로 평일 자동 녹화가 실제로 돌았는지(LastTaskResult 0이면 성공) 확인.
성공했으면 `data/ticks/`, `logs/`에서 그날 파일 확인 후 `--replay`로 관찰 시작.

## 참고 문서

- `docs/superpowers/specs/2026-09-06-tick-record-replay-design.md` — 녹화/재생
  기능 설계 스펙
- `docs/superpowers/plans/2026-09-06-tick-record-replay.md` — 구현 계획 +
  최종 리뷰 결과 + deferred 항목 목록
- `scripts/README.md` — 자동 녹화 스케줄 등록/해제/종목변경 방법
- `review.md` — 이전 세션들의 4라운드 감사 전체 기록
- `development.md` — 설치/환경변수/실행/Live 전환/녹화·재생 절차 전체 가이드
