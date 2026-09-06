# Weekday market-open auto-record. Wired to Windows Task Scheduler (see
# scripts/README.md) so it runs unattended while the user is at work.
# Exits on its own once KIS closes the daily session and reconnects are
# exhausted (see src/api/kis_websocket.py) -- no explicit stop needed here,
# but scripts/stop_record.ps1 is scheduled as a safety net after market close.
#
# The actual run is shelled out to cmd.exe: PowerShell wraps a native
# process's stderr as ErrorRecord objects even when redirected straight to
# a file, which garbles python's logging output. cmd.exe's ">>"/"2>&1" do
# plain byte redirection instead.

Set-Location "D:\BACKUP\10_교육\works\Stock"

$symbols = "005930"
$date = Get-Date -Format "yyyyMMdd"
$tickFile = "data\ticks\ticks_$date.jsonl"
$logFile = "logs\record_$date.log"

$cmd = '".\.venv\Scripts\python.exe" -m src.main ' + $symbols + ' --record "' + $tickFile + '" --status-interval 60 >> "' + $logFile + '" 2>&1'
cmd.exe /c $cmd
