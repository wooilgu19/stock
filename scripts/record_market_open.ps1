# Weekday market-open auto-record. Wired to Windows Task Scheduler (see
# scripts/README.md) so it runs unattended while the user is at work.
# Exits on its own once KIS closes the daily session and reconnects are
# exhausted (see src/api/kis_websocket.py) -- no explicit stop needed here,
# but scripts/stop_record.ps1 is scheduled as a safety net after market close.

$ErrorActionPreference = "Stop"
Set-Location "D:\BACKUP\10_교육\works\Stock"

$symbols = "005930"
$date = Get-Date -Format "yyyyMMdd"
$tickFile = "data\ticks\ticks_$date.jsonl"
$logFile = "logs\record_$date.log"

& ".\.venv\Scripts\python.exe" -m src.main $symbols.Split(" ") `
    --record $tickFile --status-interval 60 *>> $logFile
