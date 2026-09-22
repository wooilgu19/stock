# 커밋 히스토리 정리

`git log`(96커밋, 2026-08-15 ~ 2026-09-22)를 커밋별로 정리한 문서. 커밋 메시지 본문이 있는
것은 그 내용을 요약했고, 제목만 있는 초기 커밋은 코드 변경 의도를 제목에서 유추해 짧게 적었다.
전체 원문은 `git log --stat <hash>`로 확인.

## 1. 기초 구축 (2026-08-15, 트레이딩 시스템 뼈대)

| 해시 | 제목 | 목적/내용 |
|---|---|---|
| `c4c3bfe` | Implement trading system foundation | 프로젝트 기본 구조(설정, 모델, 엔진 골격) 최초 커밋 |
| `9f5bc23` | Add KIS REST authentication and price client | 한국투자증권 REST API 인증 + 시세 조회 클라이언트 추가 |
| `b93e0f0` | Add KIS realtime websocket market data pipeline | KIS 웹소켓으로 실시간 체결 데이터 수신하는 파이프라인 추가 |
| `03091bc` | Add tick inference worker and baseline strategy | 틱을 신호로 변환하는 추론 워커 + 기본 전략(이동평균) 추가 |
| `94f0c53` | Harden trading pipeline validation | 파이프라인 입력값 검증 강화 |
| `f2c16ff` | Connect signals to paper order flow | 전략 신호 → 모의투자 주문 흐름 연결 |
| `5250584` | Add order idempotency and market session guards | 중복 주문 방지(idempotency) + 장 시간 가드 추가 |
| `80c240b` | Add paper portfolio balance and position checks | 모의투자 잔고/포지션 검증 로직 추가 |
| `88f8a1a` | Restore paper portfolio state from SQLite | 재시작 시 SQLite에서 모의투자 상태 복원 |
| `fbc6922` | Support exchange holidays in market session guard | 장 시간 가드에 거래소 휴장일 반영 |
| `f7e407b` | Load market holidays from environment settings | 휴장일을 환경설정(.env)에서 읽도록 변경 |
| `52a292c` | Build market hours guard from settings | 장 시간 가드를 Settings 기반으로 생성하도록 리팩터링 |

## 2. 실계좌 연동 및 신뢰성 보강 (2026-08-16 오전)

| 해시 | 제목 | 목적/내용 |
|---|---|---|
| `eaa0035` | Require explicit executor for live orders | 실계좌 주문 시 executor를 명시적으로 지정하도록 강제(실수 방지) |
| `1dec2bc` | Add KIS cash order executor | KIS 현금 주문 실행기 추가 |
| `d00585e` | Wire settings into safe order pipeline | Settings를 안전한 주문 파이프라인에 연결 |
| `797bd02` | Add dependency health checks | 외부 의존성(Redis, KIS 등) 헬스체크 추가 |
| `ff5df5e` | Expose health readiness endpoint | 헬스체크 결과를 HTTP 엔드포인트로 노출 |
| `d22acfc` | Wire health app into settings | 헬스 앱을 Settings 기반으로 조립 |
| `90260c4` | Add broker order reconciliation | 브로커(KIS) 주문 상태와 로컬 상태 대사(reconciliation) 로직 추가 |
| `14cace3` | Apply automation mode to signal routing | AUTOMATION_MODE(auto/manual)를 신호 라우팅에 반영 |
| `19fc22c` | Assemble tick to order pipeline | 틱→신호→주문 전체 파이프라인 조립 |
| `c8c951c` | Add controllable trading runtime | 시작/정지 가능한 트레이딩 런타임 추가 |
| `d28eb34` | Add runtime application factory | 런타임 조립을 위한 애플리케이션 팩토리(`build_runtime` 계열) 추가 |
| `f794367` | Connect reconciliation to runtime | 대사 로직을 런타임에 연결 |
| `6153a6e` | Add KIS order status provider | KIS 주문 상태 조회 프로바이더 추가 |
| `68b0a03` | Wire live order reconciliation | 실계좌 주문 대사를 런타임에 배선 |
| `b1ad909` | feat: support paginated KIS order reconciliation | KIS 주문 조회가 페이지네이션될 때도 전체를 대사하도록 지원 |
| `0fdab65` | fix: keep non-terminal orders pending during reconciliation | 체결/거부 등 종결 상태가 아닌 주문은 대사 중 pending 유지하도록 수정 |
| `a7d0c62` | fix: scope realized loss to the trading day | 실현 손익 계산을 해당 거래일로 한정(일일 손실 한도 오적용 방지) |
| `d2a7508` | fix: validate broker order lifecycle statuses | 브로커가 반환하는 주문 상태값 검증 추가 |
| `0727344` | fix: normalize KIS transport failures | KIS 통신 실패를 일관된 예외로 정규화 |
| `ebef012` | fix: validate KIS access token responses | KIS 토큰 발급 응답 검증 추가 |
| `89f3c36` | feat: restore paper portfolio on startup | 시작 시 모의투자 포트폴리오 복원(88f8a1a 이후 후속 정리) |
| `40bd236` | fix: keep runtime cycles alive after component errors | 컴포넌트 하나가 오류나도 런타임 루프 전체가 죽지 않도록 수정 |
| `61c93eb` | fix: validate risk gate limits | 리스크 게이트 한도값 검증 추가 |
| `473c438` | fix: validate risk settings at startup | 시작 시 리스크 설정값 검증 |
| `b531da0` | fix: validate Redis stream payloads | Redis 스트림 페이로드 검증 추가 |
| `c33f7da` | fix: normalize trade timestamps to UTC | 거래 타임스탬프를 UTC로 통일 |
| `78c1694` | fix: harden WebSocket approval handling | 웹소켓 승인키 발급 처리 견고화 |
| `76dae28` | feat: reconnect WebSocket streams after disconnects | 웹소켓 연결 끊김 시 자동 재연결 추가 |
| `bbddcfd` | feat: add runtime metrics counters | 런타임 지표(사이클/신호/에러 수) 카운터 추가 |
| `42254c5` | feat: expose runtime metrics endpoint | 지표를 `/metrics` 엔드포인트로 노출 |
| `8f30229` | feat: add runtime error notification hook | 런타임 에러 발생 시 알림 훅 추가 |
| `ee0a9ba` | feat: add Telegram runtime notifications | 텔레그램으로 런타임 알림 전송 |
| `2212c2e` | feat: load dotenv configuration automatically | `.env` 자동 로드(`load_dotenv()`) |
| `1effedb` | feat: add deployment config validation CLI | 배포 전 설정값을 검증하는 CLI 추가 |
| `0b26258` | fix: validate domestic KIS order fields | 국내 주식 주문 필드 검증 추가 |
| `c79cd89` | fix: reject invalid runtime batch sizes | 잘못된 배치 크기 설정 거부 |
| `77d7b87` | fix: validate KIS client connection settings | KIS 클라이언트 연결 설정 검증 |
| `5b673fb` | fix: harden KIS reconciliation account handling | 대사 로직의 계좌 처리 견고화 |
| `71a7378` | feat: add explicit KIS auth smoke check | KIS 인증 스모크 테스트(수동 확인용) 추가 |
| `ec2ec27` | feat: add read-only KIS price smoke check | 읽기 전용 시세 조회 스모크 테스트 추가 |
| `8811f2b` | fix: validate symbols across KIS market data adapters | 시세 어댑터 전반에 종목코드 검증 추가 |
| `9031da2` | fix: fail fast on invalid live broker settings | 실계좌 브로커 설정이 잘못되면 즉시 실패하도록 변경 |
| `5fb00b1` | docs: add development and operations guide | 개발/운영 가이드 문서(`development.md`) 추가 |

## 3. 파이프라인 감사 및 1차 안정화 (2026-08-16 저녁 ~ 08-17)

| 해시 | 제목 | 목적/내용 |
|---|---|---|
| `515a32b` | fix: close reliability and correctness gaps found by pipeline audit | 멀티 에이전트 감사에서 발견된 문제 일괄 수정: `KIS_ENV`(paper/live) 도입 및 `Settings.is_paper` 기반 배선, SQLite 커넥션 누수 수정, `client_order_id` 충돌 시 upsert, 추론 워커 커서를 배치 단위·주문 성공 후에만 저장, H0STCNT0 다중 레코드 파싱을 실제 46필드 폭으로 수정(13으로 잘못 계산되던 버그), 체결 시각을 수신시각 대신 거래소 체결시각 사용, NaN/inf 가격 거부, "filled" 상태를 "rejected/cancelled"보다 우선 반영, 연속 거부 킬스위치 추가, 대사 주기와 틱 처리 주기 분리, 페이퍼 주문 ID 중복 제거 로직 수정, 테스트가 실제 KIS 자격증명과 격리되도록 `conftest.py` 추가 |
| `1e56abc` | feat: add production entrypoint wiring collector and trading loop | `src/main.py`: 틱 수집기(웹소켓→Redis)와 트레이딩 루프를 한 프로세스에서 함께 실행, 헬스/지표 서버 옵션 포함. 둘 중 하나가 죽으면 나머지도 같이 정지. Redis 클라이언트를 RESP2로 고정(구버전 Redis 호환) |
| `422adcd` | docs: add multi-agent audit findings and agent operating rules | `review.md`(아키텍처/퀀트/리스크게이트/성능/QA 4라운드 감사 기록)와 `AGENTS.md`(자율 에이전트 운영 규칙) 추가. `.env.example`에 `KIS_ENV` 추가 |
| `440c30f` | feat: log actionable signals and a periodic status snapshot in src.main | 콘솔에 시작 로그 한 줄만 찍히던 문제 해결: 신호 체결/거부를 즉시 로깅하는 콜백과 `--status-interval`(기본 10초) 주기 상태 스냅샷 로그 추가 |
| `cf5891d` | docs: record session handoff notes for tomorrow's continuation | 세션 인계 문서(감사 수정 내역, entrypoint, Redis 서비스, 자격증명 확인 상태, 다음 할 일) |

## 4. 틱 녹화/재생 기능 (2026-09-06)

| 해시 | 제목 | 목적/내용 |
|---|---|---|
| `937582f` | docs: add design spec for tick record/replay (off-hours observation) | 장 시간 외에도 실데이터로 파이프라인을 관찰할 수 있게 틱 녹화/재생 기능 설계 문서 작성 |
| `1e7c04d` | docs: add implementation plan for tick record/replay off-hours observation | 위 설계의 구현 계획 문서 |
| `0054690` | chore: ignore .worktrees/ for isolated feature-branch workspaces | 격리된 기능 브랜치용 워크트리 디렉터리를 gitignore에 추가 |
| `776f258` | feat: add RecordingQueue to capture ticks alongside live publishing | 실시간 발행과 동시에 틱을 파일로 녹화하는 `RecordingQueue` 추가 |
| `2445608` | fix: also catch serialization errors in RecordingQueue.publish | 직렬화 오류도 `RecordingQueue.publish`에서 잡도록 수정(녹화 실패가 전체를 죽이지 않게) |
| `1be1a04` | feat: add replay_ticks to republish recorded ticks at their original pace | 녹화된 틱을 원래 속도로 재발행하는 `replay_ticks` 추가 |
| `777c1ff` | feat: add enforce_market_hours bypass for off-hours tick replay | `enforce_market_hours` 플래그를 배선해 장 시간 외 재생 시 시간 가드를 우회할 수 있게 함(기본값은 유지) |
| `ce3b5fd` | feat: add --record/--replay flags to observe the pipeline outside market hours | `src.main`에 `--record`/`--replay` CLI 플래그 추가 |
| `fc8da7a` | docs: document --record/--replay for off-hours pipeline observation | 위 기능 사용법 문서화 |
| `0c6e0ba` | fix: close cross-task integration bugs in record/replay pipeline | 브랜치 전체 리뷰에서 발견된 통합 버그 수정: `RecordingQueue`에 `.read()`/`.ping` 위임 누락(트레이딩 루프가 매 사이클 `AttributeError`를 삼키며 틱을 0건 처리), `--replay`가 `PAPER_TRADING` 검사는 건너뛰지 않아 실계좌에 시간가드 없이 주문 나갈 수 있던 위험 제거, 재생 종료 시 마지막 배치가 유실되던 타이밍 버그에 drain 윈도우 추가, 에러 메시지/예외 처리 정리 |
| `5bbd0e6` | docs: fix heading nesting, BOM, and language in record/replay section | 문서 구조(헤딩 중첩), BOM, 언어(한국어 통일) 정리 + 재생 중복 실행 시 주의사항 기록 |
| `6102e75` | feat: schedule unattended weekday market-open tick recording | 평일 장 시작 시 `--record`를 자동 실행하는 Windows 작업 스케줄러 등록, 장 마감 후 안전장치 정지 포함 |
| `75084a8` | fix: shell out to cmd.exe for python invocation in record script | PowerShell 5.1이 stderr를 `ErrorRecord`로 감싸 python 로그를 깨뜨리고 `$ErrorActionPreference=Stop`과 겹쳐 스크립트가 중단되는 문제 수정(cmd.exe 경유). 한글 경로가 깨지지 않도록 스크립트를 UTF-8 BOM으로 저장 |
| `3dfc78a` | docs: record session handoff notes for 2026-09-06 | 세션 인계 문서 |

## 5. KIS 파싱/Redis 안정성 사고 대응 (2026-09-07 ~ 09-16)

실제 자동 수집 중 발생한 장애를 순서대로 근본 원인 분석하며 고친 시리즈.

| 해시 | 제목 | 목적/내용 |
|---|---|---|
| `949041c` | fix: tolerate trimmed trailing fields in live H0STCNT0 frames | 9/7 장 시작 직후 "필드 수 부족"으로 수집기가 크래시. 실거래 프레임이 뒤쪽 옵션 필드를 생략할 수 있음을 확인, 실제로 읽는 0~12번 필드만 필수로 완화 + 파싱 실패 1건이 전체 세션을 죽이지 않도록 skip-and-continue로 변경 (사후에 드러남: 진단이 부분적으로 틀렸고 `9bca13f`에서 진짜 원인 확인) |
| `9bca13f` | fix: H0STCNT0 record body is caret-delimited, not pipe-delimited | 9/8 하루 종일 88,551건 전량 파싱 실패. 진짜 원인은 레코드 본문 구분자가 `|`가 아니라 `^`였던 것. 구분자 수정 + 정확한 46필드 카운트 검증 복원, 실제 로그로 전량 재검증 |
| `662a3f8` | fix: don't let a transient queue.publish() failure kill the collector | 9/9 오전 중단의 원인은 Windows용 Redis 5.0.14.1의 BGSAVE 포크 크래시로 인한 연결 끊김. `RedisQueue.publish()` 실패를 틱 단위로 잡아 로깅만 하고 스트리밍은 계속하도록 수정, RDB 자동 저장도 비활성화 |
| `a1256a0` | fix: derive H0STCNT0 record width dynamically instead of hardcoding it | 9/16 KIS가 레코드 폭을 46→47필드로 무통보 변경해 전량 파싱 실패. `record_count`로 폭을 동적 계산(`len(fields)//count`)하도록 변경해 향후 폭 변경에도 견고하게 만듦 |
| `920989b` | fix: extend regular-session close time to 20:00 | 정규장 마감 시각 정책 변경(15:30→20:00)에 맞춰 시장 시간 가드 갱신 |

## 6. 전략 튜닝 및 LSTM 파이프라인 (2026-09-20)

| 해시 | 제목 | 목적/내용 |
|---|---|---|
| `00478dc` | feat: add --replay-speed for fast offline strategy tuning | 실거래 시간 동안 대기할 수 없어 재생 배속 옵션 추가(예: 60배속으로 11시간 장을 11분에 재생), 퇴근 후 임계값 튜닝 가능하게 함 |
| `6a89c6a` | fix: recalibrate strength gain so real-world crossings can pass the risk gate | 이동평균 전략의 신호 강도가 실데이터에서 최대 ~0.507로 `MIN_SIGNAL_STRENGTH`(0.60)를 절대 못 넘던 문제. 이평선 교차 시점은 스프레드가 가장 작은 순간이라 구조적으로 강도가 낮았던 것이 원인. 강도 계수(`strength_gain`)를 20→300으로 재보정(실측 스프레드 분포 기준), 전용 테스트 추가. 재생 검증 결과 승인 주문 0→6건 |
| `f155c80` | docs: add design spec for LSTM signal strategy | 3단계(딥러닝 신호 전략) 설계 문서. 아키텍처, 학습 파이프라인(윈도잉/정규화/라벨링/시간순 분리), `SignalPredictor` 프로토콜을 통한 서빙 통합, 테스트 계획, 데이터 부족 한계 명시 |
| `54ad51d` | docs: add implementation plan for LSTM signal strategy | 7개 태스크로 나눈 구현 계획(윈도잉/라벨링, 시간순 분리, `LSTMClassifier`, 학습 엔트리포인트, `LSTMStrategy`, `--strategy` CLI, 실체크포인트 스모크 테스트) |
| `e84b75b` | feat: add windowing/labeling functions for LSTM training | `sliding_windows`, `normalize_window`(초기 버전: 가격은 시작가 대비 수익률, 거래량은 log1p), `compute_future_returns`, `build_dataset`(BUY/HOLD/SELL 라벨링) 구현 + 테스트 |
| `a227fad` | feat: add chronological train/val split for LSTM training | 데이터 누수 방지를 위한 시간순 train/val 분리(`chronological_split`, 경계에 lookahead 간격 확보) |
| `c76e7a8` | feat: add small LSTMClassifier for the signal strategy | 소형 `LSTMClassifier`(hidden 16, 1층) 모델 정의 |
| `04af1fd` | feat: add LSTM training entrypoint (src/training/train.py, scripts/train_lstm.py) | `run_training()` 학습 함수와 CLI 진입점 추가. 파일/종목별로 분리해 라벨 임계값을 train 쪽 수익률로만 계산(누수 방지) |
| `4a506c9` | feat: add LSTMStrategy SignalPredictor implementation | `LSTMStrategy.on_tick(tick) -> Signal` 구현, 체크포인트 없으면 `FileNotFoundError` |
| `ca4399f` | feat: add --strategy flag to select moving-average or lstm | `src.main`에 `--strategy {moving-average,lstm}` 옵션 추가(기본 moving-average), LSTM 선택 시에만 torch 지연 로딩 |
| `d4b7711` | chore: gitignore trained LSTM checkpoints | 학습된 체크포인트(`models/*.pt`)를 gitignore에 추가 |
| `a81ce1f` | fix: prevent multi-symbol tick mixing and defer torch import to lstm strategy selection | 다종목 녹화 파일에서 서로 다른 종목의 틱이 한 시계열로 섞이던 버그 수정, torch import를 LSTM 전략 선택 시점으로 지연(불필요한 로딩 방지) |

## 7. LSTM 브랜치 머지 및 자동 수집 장애 대응 (2026-09-21)

| 해시 | 제목 | 목적/내용 |
|---|---|---|
| `9397643` | fix: retry collector reconnect when KIS approval request fails | 9/21 18:44 수집기 종료 원인 분석: `approval_key()`의 DNS 실패가 `KISWebSocketError`로 올라왔지만 재시도 대상 예외 목록에 없어 즉시 종료됨. 재시도 대상에 추가, 백오프 상한 60초, 재시도 경고 로그, `max_reconnects=30`(약 25분 장애 허용)으로 조정 |
| `bc916f6` | Merge branch 'lstm-signal-strategy' into dev | `lstm-signal-strategy` 브랜치(8커밋)를 `--no-ff`로 `dev`에 머지. 충돌 없음, 전체 테스트 178개 통과 |
| `9bd6553` | docs: record LSTM branch merge in process.md | 머지 완료를 진행 기록 문서에 반영 |
| `06b28a2` | docs: note worktree and branch cleanup | LSTM 작업용 워크트리/브랜치 삭제를 기록(모델 체크포인트도 함께 삭제됨, 재학습 필요 명시) |

## 8. LSTM 리뷰 후속 조치 (2026-09-22)

| 해시 | 제목 | 목적/내용 |
|---|---|---|
| `6be5beb` | fix: LSTM training minibatches, per-channel normalization, per-strategy risk threshold | 9/20 LSTM 리뷰에서 남겨둔 세 항목 처리: ① `train.py`가 epoch당 풀배치 1스텝(총 30스텝)만 밟아 사실상 학습이 안 되던 문제를 `DataLoader` 기반 셔플 미니배치(`--batch-size`, 기본 64)로 해결 ② `normalize_window`가 가격 수익률(±0.001대)과 `log1p(거래량)`(2~9대)를 그대로 섞어 거래량 채널이 입력을 지배하던 문제를 윈도우 단위 채널별 z-score 정규화로 해결 ③ `MIN_SIGNAL_STRENGTH`가 두 전략에 과부하(LSTM 강도는 3클래스 softmax 최댓값이라 0.333 아래로 못 내려감)되던 문제를 `RiskGate.min_signal_strength_by_strategy` + `MIN_SIGNAL_STRENGTH_LSTM` env로 전략별 분리해 해결(미설정 시 기존 값과 동일해 동작 변화 없음). 테스트 179개 통과 |

## 요약: 저장소 진화 흐름

1. **08/15~08/16**: 모의/실계좌 트레이딩 파이프라인 기초(신호→리스크게이트→주문→대사) 구축, 이어서 멀티 에이전트 감사 기반 신뢰성/정합성 대량 수정.
2. **09/06**: 장 시간 외에도 실데이터로 검증할 수 있는 틱 녹화/재생 기능 추가.
3. **09/07~09/16**: 실제 KIS 웹소켓 프레임 파싱 및 로컬 Redis 안정성 관련 실전 장애를 순차적으로 근본 원인 분석·수정.
4. **09/20**: 이동평균 전략이 실제로 주문까지 이어지도록 재보정(Phase 1), LSTM 신호 전략 파이프라인 신설(Phase 3).
5. **09/21**: LSTM 브랜치 머지, 수집기 DNS 재시도 장애 수정.
6. **09/22**: LSTM 학습 품질 개선(미니배치, 정규화) 및 리스크 게이트 전략별 임계값 분리.
