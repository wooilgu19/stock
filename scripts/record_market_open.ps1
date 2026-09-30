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

$date = Get-Date -Format "yyyyMMdd"
$tickFile = "data\ticks\ticks_$date.jsonl"
$logFile = "logs\record_$date.log"

# Daily symbols = 005930 (kept for data continuity) + the screener's picks.
# Any screener failure falls back to 005930 alone so recording never skips a day.
# Routed through cmd.exe for the same reason as the collector below (PowerShell
# mangles a native process's stderr); screener's diagnostic prints (candidate
# count, which filter tier fired) land in $logFile instead of being discarded,
# so a future empty/fallback pick is explainable from the log alone.
$pickedFile = "data\ticks\.screener_picks_$date.tmp"
cmd.exe /c ('".\.venv\Scripts\python.exe" -m src.screener 1> "' + $pickedFile + '" 2>> "' + $logFile + '"')
$picked = if (Test-Path $pickedFile) { (Get-Content $pickedFile -Raw -Encoding utf8).Trim() } else { "" }
Remove-Item $pickedFile -ErrorAction SilentlyContinue
if ($picked -notmatch '^\d{6}( \d{6})*$') { $picked = "" }
$symbols = (@("005930") + ($picked -split ' ') | Where-Object { $_ } | Select-Object -Unique) -join ' '
"$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') screener symbols=$symbols" | Out-File -Append -Encoding utf8 $logFile
# KIS allows one access-token issue per minute per app key (EGW00133); the
# screener and the collector are separate processes that each issue one.
Start-Sleep -Seconds 65

$cmd = '".\.venv\Scripts\python.exe" -m src.main ' + $symbols + ' --record "' + $tickFile + '" --status-interval 60 >> "' + $logFile + '" 2>&1'
cmd.exe /c $cmd

# A holiday run records nothing; an empty tick file would later be picked up
# as the newest day (the validation day) by scripts/train_lstm.py.
if ((Test-Path $tickFile) -and ((Get-Item $tickFile).Length -eq 0)) { Remove-Item $tickFile }
