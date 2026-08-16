# 진행 기록 (2026-08-16 세션)

다음 세션에서 이어서 개발할 때 참고용. 이 세션에서 한 일, 지금 상태, 내일 할 일 순서로 정리.

## 이 세션에서 한 일

### 1. 4라운드 멀티 에이전트 코드 감사 → `review.md`
`.claude/agents/`에 정의된 5개 서브에이전트(system-architect, quant-feature-engineer,
risk-gate, perf-infra-profiler, qa-backtest-reviewer)로 4차례 재검토를 반복했다.
발견된 문제와 수정 이력 전체가 `review.md`에 라운드별로 누적 기록되어 있다.
**다음 문제가 생기면 새 걸 처음부터 다시 찾기 전에 `review.md`부터 검색해볼 것.**

### 2. 실제 코드 수정 (커밋 `515a32b`)
- SQLite 커넥션 누수 수정 (테스트 스위트가 이거 때문에 깨져 있었음)
- 거절 주문 재시도 시 크래시하던 버그 (`save()` UPSERT로 전환)
- KIS 웹소켓 멀티레코드 파싱 stride 버그(13→46) — 가짜 틱 생성 버그였음
- 체결시각 사용, NaN 가격 검증, 부분체결+거절 시 데이터 소실 수정
- Kill-switch 추가 (`OrderManager`, 연속 3회 거절 시 자동 halt)
- reconcile 주기 분리 메커니즘, 배치 단위 커서 저장(성능)
- `tests/conftest.py`로 테스트가 실계좌 접근 못 하게 격리

### 3. 실행 엔트리포인트 `src/main.py` 신규 작성 (커밋 `1e56abc`, `440c30f`)
이전에는 조립 API만 있고 "한 방 실행" 커맨드가 없었음. 지금은:
```powershell
python -m src.main 005930 --quantity 1 --status-interval 10 --health-port 8080
```
- 웹소켓 수집기 + 매매 루프를 한 프로세스로 묶어서 실행
- 한쪽이 죽으면 다른 쪽도 같이 정지 (반쪽만 살아있는 상태 방지)
- 주기적 상태 로그(`--status-interval`) + 신호 발생 시 즉시 로그
- `Ctrl+C`/SIGTERM으로 정상 종료

### 4. 로컬 실행 환경 구성 (저장소 밖 작업)
- **Redis**: `tools/redis/`에 포터블 바이너리 다운로드 후 **Windows 서비스로 등록 완료**
  (서비스명 `Redis`, 자동 시작, 재부팅해도 살아있음 — 따로 켤 필요 없음)
- **`.env`**: 사용자가 KIS 앱키/시크릿 입력 완료, `check-kis-auth`/`check-kis-price`로 실제 인증 검증 완료
- 실제로 `src/main.py`를 여러 차례 짧게 돌려서 `/health`, `/metrics` 정상 동작 확인함

## 지금 상태 (검증됨)

- 테스트: **125개 전부 통과**
- Redis: Windows 서비스로 상시 구동 중
- KIS 인증: `.env`에 유효한 앱키/시크릿 설정됨, `paper` 모드
- `python -m src.main <종목코드>`로 실제 KIS 웹소켓 연결 + 매매 루프 + 헬스체크까지 end-to-end 확인됨
- git: 모든 변경사항 커밋 완료 (`440c30f`까지), 원격 push는 안 함

## 아직 안 된 것 (review.md "의도적으로 남겨둔 항목" 참고)

우선순위 순:

1. **평일 장중 실전 관찰** — 지금까지는 전부 주말에 테스트해서 실제 시세/신호 흐름을 본 적이 없음.
   평일 09:00~15:30(KST)에 `python -m src.main`을 돌려서 신호가 실제로 뜨는지 확인 필요.
2. **위험 한도값 검토** — `.env`의 `MAX_ORDER_VALUE`, `MAX_DAILY_LOSS`, `MIN_SIGNAL_STRENGTH`가
   지금 기본값 그대로. 사용자 본인 투자 규모에 맞게 조정 필요 (내가 대신 정할 수 없는 부분).
3. **KIS 실제 모의투자(VTTC) 계좌 연동 배선** — 지금 `PAPER_TRADING=true`는 KIS 서버에
   전혀 접속하지 않고 로컬 SQLite 시뮬레이션만 함. `KIS_ENV=paper`로 실제 KIS 모의투자
   서버까지 타는 경로는 아직 애플리케이션 배선이 없음.
4. **딥러닝 모델 연결** — 지금 전략은 `MovingAverageStrategy`(baseline) 고정.
   `models/` 디렉터리는 비어있고 실제 추론 코드 없음. 큰 작업이라 별도 세션 필요.
5. **종목별 다른 수량 설정** — `SignalOrderRouter`는 종목별 수량 매핑을 지원하지만
   `src/main.py`는 아직 `--quantity` 단일 값만 CLI로 받음.
6. **지정가/목표가 매매** — 사용자가 "이 가격 이하로 떨어지면 사줘" 같은 방식을 원하면
   지금 전략(이동평균 크로스오버)과는 다른 로직이 필요함. 이번 세션에서 논의만 하고 미착수.
7. **총 노출 한도, 미체결 자동취소, 거부 주문 알림** 등 — `review.md` 하단 "의도적으로
   남겨둔 항목" 섹션에 이유와 함께 정리되어 있음.

## 내일 시작할 때 체크리스트

```powershell
cd "D:\BACKUP\10_교육\works\Stock"
.\.venv\Scripts\Activate.ps1
python -m pytest -q                          # 125개 통과하는지 먼저 확인
python -m src.cli validate-config --live      # .env 아직 유효한지 확인
python -c "from src.queue.redis_queue import RedisQueue; RedisQueue().ping(); print('redis ok')"
```

셋 다 통과하면 세션 시작 시점과 동일한 상태. 그 다음 위 "아직 안 된 것" 목록 중
우선순위 1번(평일 실전 관찰)부터 이어가는 걸 추천.

## 참고 문서

- `review.md` — 4라운드 감사 전체 기록 + 수정 내역 + 남겨둔 항목과 이유
- `development.md` — 설치/환경변수/실행/Live 전환 절차 전체 가이드
- `.claude/agents/*.md` — 5개 검토 서브에이전트 정의
