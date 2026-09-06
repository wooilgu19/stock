# 자동 녹화 스케줄

`--record` 기능을 사용자가 직장에 있어도 평일 장중에 자동으로 돌리기 위한
Windows 작업 스케줄러 설정.

## 등록된 작업

- **StockRecordStart** — 평일(월~금) 08:55에 `record_market_open.ps1` 실행.
  종목 005930을 `data/ticks/ticks_YYYYMMDD.jsonl`에 녹화하고, 로그는
  `logs/record_YYYYMMDD.log`에 남긴다.
- **StockRecordStop** — 평일 16:00에 `stop_record.ps1` 실행. 정상적으로는
  KIS가 장 마감 후 세션을 끊으면 재연결 시도가 소진되며 프로세스가 스스로
  종료되지만(`src/api/kis_websocket.py`), 혹시 남아있을 경우를 대비한
  안전장치.

## 전제 조건

- 이 컴퓨터가 켜져 있고 네트워크에 연결되어 있어야 함 (완전 종료/절전 금지,
  화면 잠금은 무관).
- Windows 계정(`SDS`)이 로그인 상태여야 함 — 로그아웃하지 말 것.
- `.env`의 KIS 인증 정보와 Redis 서비스가 정상 동작 중이어야 함.

## 확인/해제

```powershell
Get-ScheduledTask -TaskName "StockRecordStart","StockRecordStop"
Unregister-ScheduledTask -TaskName "StockRecordStart" -Confirm:$false
Unregister-ScheduledTask -TaskName "StockRecordStop" -Confirm:$false
```

## 녹화 종목 변경

`record_market_open.ps1`의 `$symbols` 변수를 수정 (공백으로 구분해 여러
종목 지정 가능).
